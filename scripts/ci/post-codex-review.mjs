import fs from 'node:fs/promises';
import process from 'node:process';

const apiUrl = process.env.GITHUB_API_URL ?? 'https://api.github.com';
const repository = process.env.GITHUB_REPOSITORY ?? '';
const token = process.env.GITHUB_TOKEN;
const reviewContextFile = process.env.REVIEW_CONTEXT_FILE;
const reviewResultFile = process.env.REVIEW_RESULT_FILE;
const referenceReposPublicManifestFile = process.env.REFERENCE_REPOS_PUBLIC_MANIFEST_FILE;
const prNumberEnv = process.env.PR_NUMBER;
const headShaEnv = process.env.HEAD_SHA;

if (!repository.includes('/')) {
  throw new Error('GITHUB_REPOSITORY is required.');
}

if (!token) {
  throw new Error('GITHUB_TOKEN is required.');
}

if (!reviewResultFile) {
  throw new Error('REVIEW_RESULT_FILE is required.');
}

const [owner, repo] = repository.split('/');

async function githubRequest(path, { method = 'GET', body } = {}) {
  const response = await fetch(`${apiUrl}${path}`, {
    method,
    headers: {
      Accept: 'application/vnd.github+json',
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (response.status === 204) {
    return null;
  }

  const responseText = await response.text();
  const data = responseText ? JSON.parse(responseText) : null;

  if (!response.ok) {
    throw new Error(`GitHub API ${method} ${path} failed with ${response.status}: ${responseText}`);
  }

  return data;
}

function collectAddedRightSideLinesFromPatch(patch) {
  if (!patch) {
    return null;
  }

  const rightSideLines = new Set();
  let nextRightLine = null;
  let nextLeftLine = null;

  for (const line of patch.split('\n')) {
    if (line.startsWith('@@')) {
      const match = /@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);

      if (!match) {
        nextLeftLine = null;
        nextRightLine = null;
        continue;
      }

      nextLeftLine = Number(match[1]);
      nextRightLine = Number(match[2]);
      continue;
    }

    if (nextLeftLine === null || nextRightLine === null) {
      continue;
    }

    if (line.startsWith('\\')) {
      continue;
    }

    if (line.startsWith('+')) {
      rightSideLines.add(nextRightLine);
      nextRightLine += 1;
      continue;
    }

    if (line.startsWith('-')) {
      nextLeftLine += 1;
      continue;
    }

    if (line.startsWith(' ')) {
      nextLeftLine += 1;
      nextRightLine += 1;
    }
  }

  return rightSideLines;
}

async function listPullRequestFiles(prNumber) {
  const files = [];
  let page = 1;

  while (true) {
    const response = await githubRequest(
      `/repos/${owner}/${repo}/pulls/${prNumber}/files?per_page=100&page=${page}`,
    );

    files.push(...response);

    if (response.length < 100) {
      break;
    }

    page += 1;
  }

  return files;
}

async function loadReviewTarget() {
  if (reviewContextFile) {
    const rawContext = await fs.readFile(reviewContextFile, 'utf8');
    const reviewContext = JSON.parse(rawContext);

    return {
      prNumber: Number(reviewContext.pr_number),
      headSha: reviewContext.head_sha,
    };
  }

  return {
    prNumber: Number(prNumberEnv),
    headSha: headShaEnv,
  };
}

function normalizeSummary(result) {
  const summary = typeof result.summary === 'string' ? result.summary.trim() : '';

  if (summary) {
    return summary;
  }

  if (result.overall_verdict === 'lgtm') {
    return 'LGTM from Codex. I did not find any material issues in the changed code. Human approval is still required.';
  }

  return 'Codex found issues in this PR. See the inline comments and top-level notes below.';
}

function normalizeInlineComments(result, validLinesByPath) {
  const requestedComments = Array.isArray(result.inline_comments) ? result.inline_comments : [];
  const inlineComments = [];
  const downgradedNotes = [];
  const seen = new Set();

  for (const requestedComment of requestedComments) {
    const path = typeof requestedComment.path === 'string' ? requestedComment.path.trim() : '';
    const line = Number(requestedComment.line);
    const body = typeof requestedComment.body === 'string' ? requestedComment.body.trim() : '';

    if (!path || !Number.isInteger(line) || line <= 0 || !body) {
      continue;
    }

    const dedupeKey = `${path}:${line}:${body}`;

    if (seen.has(dedupeKey)) {
      continue;
    }

    seen.add(dedupeKey);

    const validLines = validLinesByPath.get(path);

    if (validLines?.has(line)) {
      inlineComments.push({
        path,
        line,
        side: 'RIGHT',
        body,
      });
      continue;
    }

    downgradedNotes.push(`- \`${path}:${line}\` ${body}`);
  }

  return { inlineComments, downgradedNotes };
}

function appendDowngradedNotes(summary, downgradedNotes) {
  const sections = [summary];

  if (downgradedNotes.length === 0) {
    return sections.join('\n\n');
  }

  sections.push(
    'The following findings could not be attached to changed lines, so they are included here as top-level notes:',
    downgradedNotes.join('\n'),
  );

  return sections.join('\n\n');
}

async function appendReviewFooter(reviewBody) {
  const sections = [reviewBody];

  if (referenceReposPublicManifestFile) {
    try {
      const manifest = (await fs.readFile(referenceReposPublicManifestFile, 'utf8')).trim();

      if (manifest) {
        sections.push(manifest);
      }
    } catch (error) {
      console.warn(`Could not read reference repo manifest: ${error.message}`);
    }
  }

  sections.push('_Automated review by Codex via GitHub Actions._');
  return sections.join('\n\n');
}

async function main() {
  const { prNumber, headSha } = await loadReviewTarget();

  if (!Number.isInteger(prNumber) || prNumber <= 0) {
    throw new Error('PR_NUMBER must be a positive integer.');
  }

  if (!headSha) {
    throw new Error('HEAD_SHA is required.');
  }

  const rawResult = await fs.readFile(reviewResultFile, 'utf8');
  const result = JSON.parse(rawResult);
  const files = await listPullRequestFiles(prNumber);
  const validLinesByPath = new Map();

  for (const file of files) {
    const validLines = collectAddedRightSideLinesFromPatch(file.patch);

    if (validLines) {
      validLinesByPath.set(file.filename, validLines);
    }
  }

  const { inlineComments, downgradedNotes } = normalizeInlineComments(result, validLinesByPath);
  const reviewBody = await appendReviewFooter(
    appendDowngradedNotes(normalizeSummary(result), downgradedNotes),
  );

  await githubRequest(`/repos/${owner}/${repo}/pulls/${prNumber}/reviews`, {
    method: 'POST',
    body: {
      commit_id: headSha,
      event: 'COMMENT',
      body: reviewBody,
      comments: inlineComments,
    },
  });

  console.log(
    `Posted Codex review for PR #${prNumber} with ${inlineComments.length} inline comment(s).`,
  );
}

await main();

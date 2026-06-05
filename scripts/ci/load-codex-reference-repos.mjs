import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';

const owner = process.env.NARADA_GITHUB_OWNER || 'NaradaAI';
const repository = process.env.GITHUB_REPOSITORY || '';
const reviewContextFile = process.env.REVIEW_CONTEXT_FILE;
const outputFile = process.env.GITHUB_OUTPUT;
const ghToken = process.env.GH_TOKEN || process.env.GITHUB_TOKEN || '';
const defaultReferenceRepos = parseList(process.env.DEFAULT_REFERENCE_REPOS || '');

const allowedRepos = new Set([
  'api-docs',
  'caddie',
  'desktop-automation-app',
  'frontend',
  'narada-python-sdk',
]);

if (!repository.includes('/')) {
  throw new Error('GITHUB_REPOSITORY is required.');
}

if (!reviewContextFile) {
  throw new Error('REVIEW_CONTEXT_FILE is required.');
}

if (!ghToken && process.env.CODEX_REFERENCE_REPOS_DRY_RUN !== 'parse') {
  throw new Error('GH_TOKEN or GITHUB_TOKEN is required.');
}

const [, currentRepo] = repository.split('/');
const reviewContext = JSON.parse(fs.readFileSync(reviewContextFile, 'utf8'));
const explicitRefs = parseCodexSiblingRefs(reviewContext.pr_body || '');

if (process.env.CODEX_REFERENCE_REPOS_DRY_RUN === 'parse') {
  console.log(
    JSON.stringify(
      {
        current_repo: currentRepo,
        default_reference_repos: defaultReferenceRepos,
        explicit_refs: Object.fromEntries(explicitRefs),
      },
      null,
      2,
    ),
  );
  process.exit(0);
}

const referenceReposDir = path.join(
  os.tmpdir(),
  `narada-reference-repos-${process.env.GITHUB_RUN_ID || process.pid}`,
);
fs.rmSync(referenceReposDir, { recursive: true, force: true });
fs.mkdirSync(referenceReposDir, { recursive: true });

const promptManifestPath = path.join(referenceReposDir, 'MANIFEST.md');
const publicManifestPath = path.join(referenceReposDir, 'PUBLIC_MANIFEST.md');
const manifestJsonPath = path.join(referenceReposDir, 'manifest.json');
const loadedRefs = [];

const reposToLoad = new Set(defaultReferenceRepos);
for (const repo of explicitRefs.keys()) {
  reposToLoad.add(repo);
}

for (const repo of [...reposToLoad].sort()) {
  if (!allowedRepos.has(repo)) {
    const explicitValue = explicitRefs.get(repo)?.trim() || '';
    if (explicitRefs.has(repo)) {
      console.warn(
        `::warning::Ignoring unsupported Codex sibling repository "${repo}". Allowed repositories: ${[...allowedRepos].sort().join(', ')}.`,
      );
      loadedRefs.push({
        repo,
        owner,
        source: 'unsupported',
        original: explicitValue,
        loaded: false,
        reason: 'unsupported sibling repository',
      });
      continue;
    }

    throw new Error(
      `Unsupported default reference repository "${repo}". Allowed repositories: ${[...allowedRepos].sort().join(', ')}.`,
    );
  }

  if (repo === currentRepo) {
    const currentRepoValue = explicitRefs.get(repo)?.trim() || '';
    if (currentRepoValue && !isSkipValue(currentRepoValue)) {
      console.warn(
        `::warning::Ignoring Codex sibling ref for ${repo}; the checked-out PR is already the review target.`,
      );
    }
    continue;
  }

  const explicitValue = explicitRefs.get(repo)?.trim() || '';
  const explicit = explicitRefs.has(repo) && explicitValue;

  if (explicitValue && isSkipValue(explicitValue)) {
    loadedRefs.push({
      repo,
      owner,
      source: 'explicit-skip',
      original: explicitValue,
      loaded: false,
      reason: 'skipped by PR body',
    });
    continue;
  }

  try {
    const ref = explicit
      ? await resolveExplicitRef(repo, explicitValue)
      : await resolveBranchRef(repo, 'main', 'default-main');
    await downloadRef(repo, ref);
    loadedRefs.push(ref);
  } catch (error) {
    if (explicit) {
      console.warn(
        `::warning::Could not load explicit Codex sibling ref for ${repo}; continuing without that snapshot. Error: ${error.message}`,
      );
      loadedRefs.push({
        repo,
        owner,
        source: 'explicit-unavailable',
        original: explicitValue,
        loaded: false,
        reason: error.message,
      });
      continue;
    }

    console.warn(
      `::warning::Could not load default ${repo}@main reference snapshot: ${error.message}`,
    );
    loadedRefs.push({
      repo,
      owner,
      source: 'default-main',
      original: 'main',
      loaded: false,
      reason: error.message,
    });
  }
}

writeManifests();
writeOutput('reference_repos_dir', loadedRefs.length ? referenceReposDir : '');
writeOutput('manifest_file', loadedRefs.length ? promptManifestPath : '');
writeOutput('public_manifest_file', loadedRefs.length ? publicManifestPath : '');
writeOutput('manifest_json_file', loadedRefs.length ? manifestJsonPath : '');

function parseList(raw) {
  return raw
    .split(/[\s,]+/)
    .map((value) => value.trim())
    .filter(Boolean);
}

function parseCodexSiblingRefs(body) {
  const refs = new Map();
  const lines = body.split(/\r?\n/);
  const startIndex = lines.findIndex((line) => /^##+\s+Codex sibling refs\s*$/i.test(line.trim()));

  if (startIndex === -1) {
    return refs;
  }

  for (const line of lines.slice(startIndex + 1)) {
    if (/^##+\s+\S/.test(line.trim())) {
      break;
    }

    const match = /^\s*[-*]\s+`?([A-Za-z0-9._-]+)`?\s*:\s*(.*?)\s*$/.exec(line);
    if (!match) {
      continue;
    }

    const repo = match[1];
    const value = stripHtmlComments(match[2]).trim();
    refs.set(repo, value);
  }

  return refs;
}

function stripHtmlComments(value) {
  let result = '';
  let cursor = 0;

  while (cursor < value.length) {
    const start = value.indexOf('<!--', cursor);
    if (start === -1) {
      result += value.slice(cursor);
      break;
    }

    result += value.slice(cursor, start);

    const end = value.indexOf('-->', start + 4);
    if (end === -1) {
      break;
    }

    cursor = end + 3;
  }

  return result;
}

function isSkipValue(value) {
  return /^(none|skip|n\/a|na)$/i.test(value.trim());
}

async function resolveExplicitRef(repo, rawValue) {
  const value = rawValue.trim();
  const pullUrlMatch = new RegExp(
    `^https://github\\.com/${owner}/([A-Za-z0-9._-]+)/pull/(\\d+)(?:\\b|$)`,
  ).exec(value);
  if (pullUrlMatch) {
    const [, urlRepo, number] = pullUrlMatch;
    assertSameRepo(repo, urlRepo, value);
    return resolvePullRequestRef(repo, Number(number), value);
  }

  const ownerPullMatch = new RegExp(`^${owner}/([A-Za-z0-9._-]+)#(\\d+)$`).exec(value);
  if (ownerPullMatch) {
    const [, shorthandRepo, number] = ownerPullMatch;
    assertSameRepo(repo, shorthandRepo, value);
    return resolvePullRequestRef(repo, Number(number), value);
  }

  const repoPullMatch = /^([A-Za-z0-9._-]+)#(\d+)$/.exec(value);
  if (repoPullMatch) {
    const [, shorthandRepo, number] = repoPullMatch;
    assertSameRepo(repo, shorthandRepo, value);
    return resolvePullRequestRef(repo, Number(number), value);
  }

  const barePullMatch = /^#(\d+)$/.exec(value);
  if (barePullMatch) {
    return resolvePullRequestRef(repo, Number(barePullMatch[1]), value);
  }

  const prMatch = /^(?:pr|pull):(\d+)$/i.exec(value);
  if (prMatch) {
    return resolvePullRequestRef(repo, Number(prMatch[1]), value);
  }

  if (/^main$/i.test(value)) {
    return resolveBranchRef(repo, 'main', 'explicit-main', value);
  }

  const shaMatch = /^(?:sha:)?([a-f0-9]{40})$/i.exec(value);
  if (shaMatch) {
    return resolveShaRef(repo, shaMatch[1].toLowerCase(), value);
  }

  const branchMatch = /^(?:branch:)(.+)$/i.exec(value);
  if (branchMatch) {
    return resolveBranchRef(repo, branchMatch[1].trim(), 'explicit-branch', value);
  }

  throw new Error(
    `Unsupported ref "${value}". Use a PR URL, ${owner}/${repo}#123, ${repo}#123, pr:123, sha:<40hex>, branch:<name>, main, or skip.`,
  );
}

function assertSameRepo(expectedRepo, actualRepo, original) {
  if (expectedRepo !== actualRepo) {
    throw new Error(
      `Ref "${original}" points at ${actualRepo}, but it was declared under ${expectedRepo}.`,
    );
  }
}

async function resolvePullRequestRef(repo, number, original) {
  if (!Number.isInteger(number) || number <= 0) {
    throw new Error(`Invalid pull request number in "${original}".`);
  }

  const pullRef = ghJson(`repos/${owner}/${repo}/git/ref/pull/${number}/head`);
  const sha = pullRef.object?.sha;

  if (!/^[a-f0-9]{40}$/i.test(sha || '')) {
    throw new Error(`Could not resolve refs/pull/${number}/head for ${owner}/${repo}.`);
  }

  const pull = tryGhJson(`repos/${owner}/${repo}/pulls/${number}`);
  if (pull?.state && pull.state !== 'open') {
    throw new Error(
      `Pull request ${owner}/${repo}#${number} is ${pull.state}; use an open PR, main, branch:<name>, sha:<40hex>, or skip.`,
    );
  }

  return {
    repo,
    owner,
    source: 'explicit-pr',
    original,
    pr_number: number,
    pr_title: pull?.title || '',
    pr_state: pull?.state || 'unknown',
    base_ref: pull?.base?.ref || '',
    head_ref: pull?.head?.ref || `refs/pull/${number}/head`,
    sha: sha.toLowerCase(),
    loaded: false,
  };
}

async function resolveShaRef(repo, sha, original) {
  const commit = ghJson(`repos/${owner}/${repo}/commits/${sha}`);
  const resolvedSha = commit.sha;
  if (resolvedSha?.toLowerCase() !== sha.toLowerCase()) {
    throw new Error(`Commit ${sha} could not be verified in ${owner}/${repo}.`);
  }

  return {
    repo,
    owner,
    source: 'explicit-sha',
    original,
    sha: sha.toLowerCase(),
    loaded: false,
  };
}

async function resolveBranchRef(repo, branch, source, original = branch) {
  assertSafeBranchName(branch);
  const branchData = ghJson(`repos/${owner}/${repo}/branches/${encodeURIComponent(branch)}`);
  const sha = branchData.commit?.sha;
  if (!/^[a-f0-9]{40}$/i.test(sha || '')) {
    throw new Error(`Could not resolve ${owner}/${repo}@${branch}.`);
  }

  return {
    repo,
    owner,
    source,
    original,
    branch,
    sha: sha.toLowerCase(),
    loaded: false,
  };
}

function assertSafeBranchName(branch) {
  const result = spawnSync('git', ['check-ref-format', '--branch', branch], {
    encoding: 'utf8',
  });

  if (result.status !== 0 || branch.includes('@{')) {
    throw new Error(`Invalid branch name "${branch}".`);
  }
}

async function downloadRef(repo, ref) {
  const repoDir = path.join(referenceReposDir, repo);
  const archive = path.join(referenceReposDir, `${repo}-${ref.sha}.tar.gz`);
  fs.rmSync(repoDir, { recursive: true, force: true });
  fs.mkdirSync(repoDir, { recursive: true });

  ghDownload(`repos/${owner}/${repo}/tarball/${ref.sha}`, archive);
  assertTarballLooksSafe(archive);

  const extractResult = spawnSync(
    'tar',
    [
      '-xzf',
      archive,
      '--strip-components=1',
      '--no-same-owner',
      '--no-same-permissions',
      '-C',
      repoDir,
    ],
    {
      encoding: 'utf8',
    },
  );

  if (extractResult.status !== 0) {
    throw new Error(`tar extraction failed: ${extractResult.stderr || extractResult.stdout}`);
  }

  assertExtractedTreeLooksSafe(repoDir);

  ref.path = repoDir;
  ref.loaded = true;
}

function assertTarballLooksSafe(archive) {
  const result = spawnSync('tar', ['-tzf', archive], {
    encoding: 'utf8',
    maxBuffer: 50 * 1024 * 1024,
  });
  if (result.status !== 0) {
    throw new Error(`tar listing failed: ${result.stderr || result.stdout}`);
  }

  const entries = result.stdout.split('\n').filter(Boolean);
  if (entries.length === 0) {
    throw new Error('archive is empty');
  }

  if (entries.length > 100000) {
    throw new Error(`archive has too many entries (${entries.length})`);
  }

  for (const entry of entries) {
    assertSafeArchivePath(entry);
  }

  const verboseResult = spawnSync('tar', ['-tvzf', archive], {
    encoding: 'utf8',
    maxBuffer: 50 * 1024 * 1024,
  });
  if (verboseResult.status !== 0) {
    throw new Error(`tar verbose listing failed: ${verboseResult.stderr || verboseResult.stdout}`);
  }

  for (const line of verboseResult.stdout.split('\n').filter(Boolean)) {
    const type = line[0];
    if (type === 'l' || type === 'h') {
      const linkTarget = line.split(' -> ')[1]?.trim();
      if (!linkTarget) {
        throw new Error(`archive contains link entry without target: ${line}`);
      }
      assertSafeArchivePath(linkTarget);
    }
  }
}

function assertSafeArchivePath(entry) {
  if (entry.startsWith('/') || entry.split('/').includes('..')) {
    throw new Error(`unsafe archive entry: ${entry}`);
  }
}

function assertExtractedTreeLooksSafe(rootDir) {
  const pending = [rootDir];

  while (pending.length) {
    const current = pending.pop();
    const stat = fs.lstatSync(current);

    if (stat.isSymbolicLink()) {
      const target = fs.readlinkSync(current);
      const resolvedTarget = path.resolve(path.dirname(current), target);
      const relativeTarget = path.relative(rootDir, resolvedTarget);

      if (relativeTarget.startsWith('..') || path.isAbsolute(relativeTarget)) {
        throw new Error(
          `extracted archive symlink escapes target directory: ${path.relative(rootDir, current)} -> ${target}`,
        );
      }

      continue;
    }

    if (!stat.isDirectory()) {
      continue;
    }

    for (const child of fs.readdirSync(current)) {
      const childPath = path.join(current, child);
      const relative = path.relative(rootDir, childPath);

      if (relative.startsWith('..') || path.isAbsolute(relative)) {
        throw new Error(`extracted archive escaped target directory: ${childPath}`);
      }

      pending.push(childPath);
    }
  }
}

function ghJson(apiPath) {
  const result = spawnSync('gh', ['api', apiPath], {
    encoding: 'utf8',
    env: { ...process.env, GH_TOKEN: ghToken },
    maxBuffer: 20 * 1024 * 1024,
  });

  if (result.status !== 0) {
    throw new Error((result.stderr || result.stdout || `gh api ${apiPath} failed`).trim());
  }

  return JSON.parse(result.stdout);
}

function tryGhJson(apiPath) {
  try {
    return ghJson(apiPath);
  } catch {
    return null;
  }
}

function ghDownload(apiPath, outputPath) {
  const fd = fs.openSync(outputPath, 'w');
  const result = spawnSync('gh', ['api', apiPath], {
    stdio: ['ignore', fd, 'pipe'],
    env: { ...process.env, GH_TOKEN: ghToken },
  });
  fs.closeSync(fd);

  if (result.status !== 0) {
    throw new Error((result.stderr?.toString() || `gh api ${apiPath} failed`).trim());
  }
}

function writeManifests() {
  const promptLines = ['# Read-only reference repositories', ''];
  const publicLines = ['### Codex Reference Context', ''];

  for (const ref of loadedRefs) {
    if (!ref.loaded) {
      const line = `- ${owner}/${ref.repo}: not loaded (${ref.source}; ${ref.reason})`;
      promptLines.push(line);
      publicLines.push(line);
      continue;
    }

    const label = formatRefLabel(ref);
    promptLines.push(`- ${label}: ${ref.path}`);
    publicLines.push(`- ${label}`);
  }

  fs.writeFileSync(promptManifestPath, `${promptLines.join('\n')}\n`);
  fs.writeFileSync(publicManifestPath, `${publicLines.join('\n')}\n`);
  fs.writeFileSync(manifestJsonPath, `${JSON.stringify(loadedRefs, null, 2)}\n`);
}

function formatRefLabel(ref) {
  const sha = ref.sha.slice(0, 12);
  if (ref.source === 'explicit-pr') {
    return `${owner}/${ref.repo}#${ref.pr_number}@${sha} (explicit sibling PR; ${ref.head_ref} -> ${ref.base_ref})`;
  }

  if (ref.source === 'explicit-main') {
    return `${owner}/${ref.repo}@${sha} (explicit main)`;
  }

  if (ref.source === 'explicit-sha') {
    return `${owner}/${ref.repo}@${sha} (explicit SHA)`;
  }

  if (ref.source === 'explicit-branch') {
    return `${owner}/${ref.repo}@${sha} (explicit branch: ${ref.branch})`;
  }

  return `${owner}/${ref.repo}@${sha} (default main)`;
}

function writeOutput(name, value) {
  if (!outputFile) {
    return;
  }

  fs.appendFileSync(outputFile, `${name}=${value}\n`);
}

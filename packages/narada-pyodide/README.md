This is a Pyodide-compatible slim implementation for the [actual Narada Python SDK](https://github.com/NaradaAI/narada-python-sdk/narada), intended for internal use only.

## Operator Memory

Use the same optional key as the native SDK when a saved Agent Studio Python
workflow calls Operator or Operator Mini:

```python
result = await operator.run(prompt, operator_memory_key="booking-rates")
```

Keep the key stable for one logical step and share it only within the intended
organization. DEV and PROD use separate policies. Check
`result.operator_memory` for the review outcome and whether its charges are
included in the result's usage. Review uses the remaining call deadline. Omit
the key for ordinary Operator calls, including calls with a critic.

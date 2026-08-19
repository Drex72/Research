# Compatibility package

The independent implementation now lives in
[`src/csrt_codeswitch`](../../../csrt_codeswitch/README.md).

This directory only preserves the old `csrt_mas.codeswitch` import path for
legacy experiments. New code should use:

```python
from csrt_codeswitch import CodeSwitcher
```

# artifacts/

Operator-local run products land here as `artifacts/<run-id>/` after they are produced.

- Small text / JSON / plots may be committed.
- `*.pth` `*.pt` `*.onnx` `*.mp4` and archives go through Git LFS or a GitHub Release — never silently into PR #4.
- Default walk stays **344→13**. `TRAINABLE=false`. See [LOCAL-RUN-ARTIFACTS.md](../../docs/LOCAL-RUN-ARTIFACTS.md).

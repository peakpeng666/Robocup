# research 分支文档入口

`main` 没有 `research/` 目录。活的论文清单与落地路线在 **`origin/research`**。
本机已保存的火神审阅在 `main`，不要把两条线混成「已经合入实现」。

## 在 `main` 上读（不切换分支）

```bash
git fetch origin research
git show origin/research:research/02-论文清单.md
git show origin/research:research/06-落地路线建议.md
git show origin/research:research/survey/B-感知与反应技能.md
```

浏览整棵目录：

```bash
git ls-tree -r --name-only origin/research -- research/
```

## GitHub

- 分支根：[research/](https://github.com/peakpeng666/Robocup/tree/research/research)
- [02-论文清单.md](https://github.com/peakpeng666/Robocup/blob/research/research/02-论文清单.md)
- [06-落地路线建议.md](https://github.com/peakpeng666/Robocup/blob/research/research/06-落地路线建议.md)

`06` 里的 P0–P5 是「4096 env 实验矩阵」，**不是**本 PR 的 P0（合同门禁）。

## `main` 上已有、不必去 research 分支的

| 文件 | 内容 |
|---|---|
| [huoshen_findings.md](../research-materials-20261019/k1-soccer-lab/docs/evidence/huoshen_findings.md) | 火神 T1 审阅（真机不是 K1） |
| [SURVEY-20261024-motion-policy-rl.md](SURVEY-20261024-motion-policy-rl.md) | 本仓现状与合同 |
| [NEXT-P1-P2.md](NEXT-P1-P2.md) | 以官方步态为基线的 P1/P2 操作手册 |
| [ROADMAP-P0-P5.md](ROADMAP-P0-P5.md) | 全球实践映射后的 P0–P5（本 PR 命名） |
| [GLOBAL-HUMANOID-SURVEY-20261024.md](GLOBAL-HUMANOID-SURVEY-20261024.md) | 全球人形平台/开源栈/足球方法 |
| [SKILL-SWITCH-CONTINUITY.md](SKILL-SWITCH-CONTINUITY.md) | 走↔踢↔反应：历史/相位/力矩验收清单（空壳） |
| [HIFAR-VS-STANDUP.md](HIFAR-VS-STANDUP.md) | HiFAR ≠ 普通起身 73→22 / 快速起身 72→22 |
| [policy-contract-v1.md](policy-contract-v1.md) | walk 344→13 / kick 59→13 / standup 73→22 |

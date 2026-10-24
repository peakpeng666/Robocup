# TeamComm 128 vs 512（用途不同，不得混用）

官方 B-Human `TeamMessageContainer::data[128]` 是规则书**机载容器**长度。  
HSL GameController 队消息预算是 **512 B**（UDP `10000+队号` 的载荷上限）。

二者**用途不同**，**不得混用**数字：

- **不得用 512 覆盖**官方 128 容器（也不得把 `data[128]` 改写成 `data[512]` 冒充已对齐）。
- **不得把 128 误标**成「HSL 预算已满足」。128 满足的是规则书容器，不是 512 预算验收。
- 不得用 512 覆盖官方 128 之后，再把 128 写成「已经按 HSL 过了」。

Walk 主路径仍是官方 **344→13**。队友 / 压缩报文不得写入 344。

**带宽**实测：无机器人 / 无 WLAN → **SKIP**。SKIP ≠ 预算已满足，更 ≠ 可以把 128 和 512 当成同一个数。

可测断言：`k1-switcher/teamcomm_128_vs_512.py`。形状 stub 仍见 `compressed_teamcomm_shape.py`。

本轮加深（只读 overlay）：`scripts/teamcomm_shape_negatives.py`（**TRAINABLE=false**；**gap_closed=false**）。再钉 **128 ≠ 512** / CompressedTeamComm 类型界，并拒绝 `silent_teamcomm_size_upgrade`（不得把 `data[128]` 静默改成 `data[512]`，也不得把 128 标成 HSL 已满足）。带宽无机器人 / 无 WLAN 仍 SKIP。

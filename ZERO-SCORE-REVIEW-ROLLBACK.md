# 0% 一次性复核与回退

首次合法评分恰好为 0% 时，系统默认使用同一证据包和首次 JSON 额外调用一次 Hermes。该步骤不重新搜索、不改变 validator、不强制产生非零结果，并且最多执行一次。

复核输出无效、来源越界或未通过 validator 时，系统保留首次合法 0%，公司状态仍为 `valid`。审计产物包括：

- `hermes-raw-zero-review.txt`
- `hermes-usage-zero-review.json`
- `result.json` 中的 `research.zero_score_review`

## 临时关闭

在原运行命令末尾加入：

```bash
--no-zero-review
```

关闭后，合法 0% 与未启用复核时相同，只执行首次研究。

Python 调用方也可以将 `review_zero_score=False` 传给底层研究函数。永久移除该功能时，只需删除研究提示、首次合法 0% 后的复核分支、CLI 参数传递和对应测试；无需修改检索、评分 validator 或产品契约。

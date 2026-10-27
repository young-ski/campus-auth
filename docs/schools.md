# 学校适配层目录

这里只做索引，代码在哪写在哪。**加一行不需要权限**，提 PR 或直接开 issue 都行。

状态说明：`已验证` = 有人在自己的真机上跑通过；`待验证` = 结构对得上但没人确认过；
`模板` = 骨架，要改。

| 学校 | 门户 | 适配层 | 状态 | 维护者 |
| --- | --- | --- | --- | --- |
| 河南城建学院 | `netauth.huuc.edu.cn:802` | 本仓 `adapters/huuc.py` | 已验证 | @young-ski |
| 未具名学校 | `10.0.0.1:8080` | 本仓 `adapters/example_generic.py` | 模板 | @young-ski |
| 你的学校？ | — | 提 issue 或 PR 加一行 | 待验证 | 你 |

## 两种放法

**放在主仓**（推荐，能被 `adapters` 命令列出来、跟版本一起发）：
按 [`CONTRIBUTING.md`](../CONTRIBUTING.md) 的「加一所学校」走。

**放在自己的仓库**（不想改主仓、或还没准备好 PR）：
`--adapter` 接受 `路径.py:属性名` 或 `模块:属性名`，文件里只要有一个 `Adapter` 实例即可：

```bash
campus-auth status --adapter ./my_school.py:ADAPTER --url http://10.0.0.9:8080
```

三条边界先知道：

1. 它依赖本仓的 `Adapter` 接口，属于内部 API，升级时可能被改动 —— 请锁版本（`pip install "campus-auth==1.4.*"`）。
2. 放外面不会被 CI 覆盖，也进不了 `adapters` 列表。
3. 用的是你本机的 Python，模拟器/容器里要自己装好依赖。

跑通了就把这一行补进来，别人少走一遍。

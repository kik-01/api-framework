# 接口自动化测试框架

基于 **Python + pytest + requests + YAML** 的接口自动化测试框架。

被测对象：JSONPlaceholder 公开 API（外部契约验证）+ 本地 mock 服务（落库校验）。

**当前状态**：31 条用例，28 通过 + 3 条标记为预期失败（xfail）。

---

## 特性

- **分层架构**：配置 / 客户端 / 断言 / 用例四层，用例层只写业务断言，框架层处理鉴权、超时、重试与日志
- **数据驱动**：测试数据与预期结构放在 YAML，新增用例只加数据行，不改测试逻辑
- **资源管理**：pytest fixture 负责创建与清理，用例之间互不污染
- **落库校验**：接口返回与数据库实际值对账，能识别「返回 200 但未写库」的假成功
- **持续集成**：GitHub Actions 在 push 时自动执行，产物上传为 artifact

## 技术选型

| 组件 | 选择理由 |
|---|---|
| pytest | `@parametrize` 做数据驱动，`fixture` 控制作用域，断言直接用 `assert`，失败信息清晰 |
| requests | HTTP 客户端事实标准，Session 可复用连接，降低批量执行的握手开销 |
| PyYAML | 测试数据带注释、易 diff，比 Excel 更适合版本管理 |
| sqlite3 | 被测服务为本地 mock，免安装免密码，CI 可直接运行；切换 pymysql 只需替换 connect 部分 |

## 目录结构

```
api-framework/
├── config/test/config.yaml    # 环境配置（base_url / 超时 / 重试次数）
├── data/post_data.yaml        # 测试数据、响应结构基线、性能基线
├── common/                    # 框架层
│   ├── settings.py            # 配置加载与路径管理
│   ├── api_client.py          # HTTP 封装（鉴权 / 超时 / 日志 / 重试）
│   ├── validators.py          # 断言工具（失败时携带响应上下文）
│   ├── db.py                  # 数据库访问，用于落库校验
│   ├── local_api.py           # 本地被测服务，真实写入 SQLite
│   └── logger.py              # 日志（控制台 info + 文件 debug）
├── testcases/
│   ├── conftest.py            # fixture：client、数据加载、本地服务生命周期
│   ├── test_posts.py          # 25 条：查询 / 写入 / 参数化 / 异常 / 性能 / 依赖链
│   └── test_db_consistency.py # 6 条：接口返回与落库一致性
├── .github/workflows/ci.yml   # GitHub Actions
├── check_env.py               # 环境自检（Python 版本 / 依赖 / 配置 / 网络）
├── pytest.ini
└── requirements.txt
```

## 快速开始

需要 Python 3.10+，网络能访问 jsonplaceholder。

```bash
# 0. 先自检：Python 版本 / 依赖 / 配置 / 网络，一次查完
py check_env.py

# 1. 安装依赖（只需一次）
py -m pip install -r requirements.txt

# 2. 跑
py -m pytest                    # 全部用例
py -m pytest -m smoke           # 冒烟
py -m pytest -v                 # 带请求/响应日志
```

> Windows 建议用 `py`（Python Launcher，会自动选装了依赖的解释器）；若 `py` 不可用，用 `python -m pytest`，但要确认该解释器装过 `requirements.txt`。
> 遇到问题先跑 `py check_env.py`，它会指出是版本、依赖、配置还是网络的问题。

预期输出：

```
testcases/test_db_consistency.py ......                          [ 19%]
testcases/test_posts.py ....................xx..x                [100%]
======================= 28 passed, 3 xfailed =======================
```

## 用例覆盖

| 分组 | 内容 | 数量 |
|---|---|---|
| 查询 | 列表 / 单条 / 带查询参数 / 结构校验 | 4 |
| 写入 | POST / PUT / PATCH / DELETE | 4 |
| 参数化 | 4 组数据 × 创建 + 5 个 id × 查询 | 9 |
| 异常 | 404 / 非法 id / 错误方法 / 缺必填 / 类型错误 | 5 |
| 性能 | 响应时间基线 | 1 |
| 依赖链 | 创建 → 使用 → 清理 | 2 |
| 落库校验 | 接口返回与数据库实际值对账 | 6 |
| **合计** | | **31** |

### 落库校验

只断言状态码与响应体的用例，在「异步写 / 事务回滚 / 主从延迟」三种情况下同样会通过，但未验证任何数据。

`common/db.py` 补上了查库对账：用接口返回的 id 查询数据库并比对字段值。
被测服务 `common/local_api.py` 中的 `/users/broken` 端点返回 200 但不写库，
用于验证该校验确实能识别假成功，而非形同虚设。

## 关键问题与处理

四个坑都按「现象 → 排查 → 根因 → 修复」记录，面试时按这张表讲即可。

| 问题 | 现象 | 排查 | 根因 | 修复 |
|---|---|---|---|---|
| 列表接口读超时 | `GET /posts` 不带参数时用例报 `ReadTimeout`（10s 超时） | 先看日志确认是超时而非 4xx；请求加 `_limit=10` 后立即通过；对比响应体大小，确认是返回 100 条导致 | 接口默认返回全量数据，测试请求未分页；公网延迟叠加 | 请求固定带 `_limit=10`；`config.yaml` 超时放宽至 30s |
| mock 服务不持久化 | `POST /posts` 返回 201 与 id=101，随后 `GET /posts/101` 返回 404 | 确认 POST 响应正常、换 id 仍 404；查文档确认 jsonplaceholder 不落库 | mock 服务只回显请求，不真正持久化 | 依赖真实写入的 3 条用例标 `xfail` 并注明原因；另起本地 SQLite 服务验证落库链路 |
| YAML 类型名被解析为字符串 | 结构校验抛 `TypeError: isinstance() arg 2 must be a type` | 打印 schema，发现取到的是字符串 `"int"` 而不是 `int` 类型 | YAML 没有「类型」这种数据类型，`int` 只是普通字符串 | `validators.py` 建立 `TYPE_MAP` 名称到类型的映射；顺带特判 `bool`（它是 `int` 子类） |
| 重试边界设计 | 初期对所有失败都重试，4xx 也在重试，耗时增加且写操作有重复风险 | 按日志把失败分类，发现 4xx 重试结果完全一致 | 未区分「瞬时故障」与「确定性错误」 | 只重试 `Timeout` / `ConnectionError` / `5xx`；线性退避 1.5s→3s→4.5s；次数在 `config.yaml` 配置 |

## 已知限制

1. **数据隔离不足**：落库校验共用本地 SQLite，并发执行会相互干扰，需要用例级唯一数据或执行后清理
2. **CI 覆盖不全**：已接入 GitHub Actions，但未接报告发布（Pages）与失败通知
3. **结构校验简单**：手写的 `assert_schema` 不支持嵌套、枚举、正则，复杂场景应改用 jsonschema
4. **仅支持 SQLite**：真实项目需替换为 pymysql，并处理连接池与主从延迟

## 后续计划

- [ ] 用 `pytest_generate_tests` 实现真正的动态数据驱动
- [ ] Allure 结果发布到 GitHub Pages
- [ ] 增加 staging 环境配置，通过 `TEST_ENV` 切换
- [ ] 接入 jsonschema 替换手写结构校验

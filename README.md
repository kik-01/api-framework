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
├── pytest.ini
└── requirements.txt
```

## 快速开始

```bash
pip install -r requirements.txt

python -m pytest                    # 全部用例
python -m pytest -m smoke           # 冒烟
python -m pytest -v                 # 带请求/响应日志
```

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

| 问题 | 处理 |
|---|---|
| 列表接口 `ReadTimeout` | 该接口不带参时一次返回 100 条记录，公网延迟下超出 10s 超时。请求加 `_limit=10`，超时放宽至 30s |
| mock 服务不持久化 | `POST` 返回的 id 无法查询，链路用例必然失败。标记为 `xfail` 并注明原因，指向真实接口时移除标记 |
| YAML 类型名被解析为字符串 | `int` 在 YAML 中是字符串 `"int"`，直接传给 `isinstance` 抛 `TypeError`。在 `validators.py` 中建立名称到类型的映射 |
| 公开 API 响应不稳定 | 同一请求耗时从 300ms 到 30s 不等。在 `api_client.py` 中加自动重试：只重试超时、连接错误与 5xx，采用递增退避，次数可配置 |

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

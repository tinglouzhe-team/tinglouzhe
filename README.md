# 听漏者 · 公网永久版

压缩空气管网泄漏定位与修复决策智能体。
**零第三方依赖**：只用 Python 标准库，本地双击就能跑，放到 Render 上就能得到一个永久 `https://` 链接。

> 从零开始的完整操作步骤，看同目录配套文档《零基础搭建教程_永久链接版.docx》。
> 只想快点动手，看 `部署速查卡.txt`。

---

## 一、本机跑起来（1 分钟）

1. 装 Python 3.10+：<https://www.python.org/downloads/>（安装第一屏勾选 **Add Python to PATH**）
2. 双击 `run.bat`
3. 浏览器打开 <http://127.0.0.1:8000>

右上角显示「本地规则模式 · 离线可用」＝ 成功，全程不需要联网、不需要 API Key。

换端口：命令提示符里 `set PORT=8010 && python app.py`；PowerShell 里 `$env:PORT=8010 ; python app.py`。

---

## 二、部署到公网（得到永久链接）

1. 把本文件夹里的文件传到 GitHub 仓库（网页拖拽即可，**别传压缩包**）。
2. <https://render.com> 用 GitHub 账号登录（免费，不要信用卡）。
3. `+ New` → `Web Service` → 选仓库 → `Connect`。
4. 照下表填，其余别看：

| 字段 | 填什么 |
|---|---|
| Name | `tinglouzhe`（这就是链接前半段） |
| Branch | `main` |
| Language | `Python 3` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python app.py` |
| Compute | `Free` |

5. 点 Deploy，等 3—10 分钟，日志出现 `==> Your service is live 🎉` 即成功。
6. 链接：`https://你的名字.onrender.com`

免费实例 15 分钟没人访问会休眠，下次打开等约 1 分钟；每月 750 实例小时，休眠不扣。

---

## 三、文件都是干嘛的

| 文件 | 作用 | 你要不要改 |
|---|---|---|
| `app.py` | 网页服务，接收请求、返回页面和 JSON | 不用改 |
| `engine.py` | 全部公式与计算（纯函数） | 懂公式可以改 |
| `agent.py` | 智能体人设、五个工具、规则兜底 | **改提示词，这是精华** |
| `doctor.py` | 模型配置体检（本地用） | 不用改 |
| `data/network.json` | 车间与漏点数据 | **一定要改成你们的** |
| `web/` | 页面：index.html / style.css / app.js | 可改颜色文字 |
| `tests/` | 14 个单元测试 + 22 项接口检查 | 不用改 |
| `pythonanywhere_wsgi.py` | 备用通道（PythonAnywhere）专用 | 备用时才用 |
| `run.bat` | Windows 双击启动 | 不用改 |

---

## 四、自测（答辩时能当证据）

```
python tests\test_engine.py            # 单元测试 14 个
python app.py                          # 另开一个窗口
python tests\smoke_test.py             # 接口检查 22 项
```

当前结果：**单元测试 14/14 通过，接口检查 22/22 通过**。
接口测试也支持指定地址：`python tests\smoke_test.py https://你的链接.onrender.com`。

---

## 五、换成你们自己的数据

改 `data/network.json` 里的 `zones` 和 `leaks`，云端改完提交后会自动重新部署。

```json
"zones": [ {"name": "你们的车间", "header_flow": 20, "branches": [7, 6, 5]} ],
"leaks": [ {"location": "具体漏点", "flow": 0.4, "cost": 800} ]
```

方案书里要写明"教学仿真数据"，不要当成企业实测值。

---

## 六、说明

- 全部数据为教学仿真，非真实企业实测。
- 方法参照 ISO 11011 停机保压法；压力—能耗经验值取 7%/bar，实际项目以厂家样本为准。
- 泄漏率判级区间（10/20/30%）为行业经验值，引用时注明来源。

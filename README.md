<div align="center">

# DY_SparkAutoKeeper

**DouYin网页版火花自动维护工具**

基于 Playwright 的本地自动化方案 —— 每天在指定时间自动为好友续上火化，无需人工值守。

[![Version](https://img.shields.io/badge/version-1.2.0-E8935A)](https://github.com/YHAz1/DY_SparkAutoKeeper/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-blue)](https://github.com/YHAz1/DY_SparkAutoKeeper/releases)
[![Engine](https://img.shields.io/badge/engine-Playwright%20·%20Chromium-2EAD33)](https://playwright.dev/python/)
[![GUI](https://img.shields.io/badge/GUI-PyQt5-41CD52)](https://www.riverbankcomputing.com/software/pyqt/)
[![Issues](https://img.shields.io/github/issues/YHAz1/DY_SparkAutoKeeper-E8935A)](https://github.com/YHAz1/DY_SparkAutoKeeper/issues)
[![License](https://img.shields.io/badge/license-Restricted-red)](#-免责声明)

**本项目仅供个人学习与技术交流使用。下载或使用前请务必阅读[免责声明](#-免责声明)。**

</div>

---

## 目录

- [功能特性](#-功能特性)
- [快速开始](#-快速开始)
- [使用指南](#-使用指南)
- [配置说明](#-配置说明)
- [定时与唤醒机制](#-定时与唤醒机制)
- [项目结构](#-项目结构)
- [常见问题](#-常见问题)
- [反馈与支持](#-反馈与支持)
- [免责声明](#-免责声明)
- [许可证](#-许可证)

---

## ✨ 功能特性

### 核心
- **定时自动发送**：每日在指定时间向一位或多位好友自动发送 `[续火花吧]`（抖音自动将文本转为火花表情），维持火花不断
- **智能会话定位**：自动打开消息面板，对会话列表逐屏扫描定位目标好友——无论对方排在列表什么位置均可命中；面板内搜索作为二级兜底
- **发送结果双信号确认**：以「聊天窗口内容变化」+「输入框清空」双重信号判定真实送达，杜绝假成功

### 调度
- **双通道自启**：Windows 任务计划程序每日定时触发 + 启动文件夹登录检查兜底
- **智能补发**：错过定点（关机/睡眠）后，下次开机登录自动检测并立即补发
- **睡眠唤醒**：注册任务自带 `WakeToRun` 参数，电脑睡眠中也可按时唤醒执行
- **单实例保护**：文件锁防止多实例并发重复发送

### 可靠性与拟人化
- 随机延迟 + 逐字键入模拟真人输入节奏
- 好友定位失败自动降级：滚动查找 → 面板内搜索 → 刷新重试
- 发送时间输入自动纠错：`9：5`、`9点30`、`930`、`２１` 等写法均自动转为标准 `HH:MM`
- 发送记录原子写入，异常断电不会导致状态损坏或重复发送

### 界面（PyQt5）
- 图形化管理好友列表、发送时间/内容、重试参数、GPU 渲染开关
- 一键注册/删除自启任务、一键手动运行、实时运行日志
- 可选「每日任务后自动随机明日发送时间」（9:00–22:00 区间）

---

## 📦 快速开始

### 方式一：打包版（推荐，开箱即用）

1. 从 [Releases](https://github.com/YHAz1/DY_SparkAutoKeeper/releases) 下载 `DY_SparkAutoKeeper_vX.X.X_win64.zip`
2. 解压到任意目录（路径建议不含特殊字符）
3. 双击 `app.exe` 启动控制面板
4. 首次使用点击「立即运行一次」，在弹出的浏览器中扫码登录抖音
5. 添加好友备注、设置发送时间，点击「注册自启任务」即可

> 内置 Chromium 与全部依赖，**无需安装 Python 或任何环境**。
> 程序无数字签名，若出现 SmartScreen 提示，点击「更多信息 → 仍要运行」。

### 方式二：源码运行（开发者）

环境要求：Windows 10/11、Anaconda（或 Miniconda）

```bat
:: 1. 创建独立 conda 环境 dy_spark 并安装依赖（Playwright、PyQt5 等）
app\scripts\install.bat

:: 2. 启动图形设置面板
app\scripts\start_gui.bat

:: 3. 或直接命令行执行一次发送任务
conda run -n dy_spark python app\main.py
```

---

## 🚀 使用指南

| 步骤 | 操作 | 说明 |
|---|---|---|
| 1 | 扫码登录 | 仅首次需要，登录态持久化在本机，之后自动复用 |
| 2 | 添加好友 | 填写你对该好友的**备注名**，需与对方有过私信记录 |
| 3 | 设置时间 | 24 小时制 `HH:MM`，支持多种非规范写法自动纠正 |
| 4 | 注册自启任务 | 同时创建「每日定时触发」与「登录检查」两条通道 |
| 5 | 完成 | 之后每天自动执行；可在面板实时查看运行日志 |

---

## ⚙️ 配置说明

所有配置保存在程序目录下的 `config.yaml`，可通过 GUI 修改，也可直接编辑：

| 配置项 | 说明 | 默认值 |
|---|---|---|
| `send_time` | 每日发送时间（HH:MM） | `09:00` |
| `friends` | 好友备注名列表 | `[]` |
| `message.text` | 发送内容（抖音自动转为对应表情） | `[续火花吧]` |
| `randomize_time` | 每日任务完成后自动随机明日发送时间（9:00–22:00） | `false` |
| `delays.min/max` | 输入前后拟人化随机延迟范围（秒） | `1.0 / 3.0` |
| `retry.max_attempts` | 单个好友失败重试次数 | `3` |
| `browser.headless` | 无头模式（后台运行不显示窗口） | `false` |
| `browser.gpu` | GPU 渲染加速 | `true` |
| `log.keep_days` | 日志保留天数 | `30` |

> **数据隐私**：登录态（`data/profile`）、发送记录（`data/state.json`）、日志（`logs/`）全部仅存储于本机，本程序不做任何网络上传。

---

## ⏰ 定时与唤醒机制

| 电脑状态 | 行为 |
|---|---|
| 正常使用中 / 锁屏 | 到点准时执行 |
| 睡眠 | 通过任务计划的 `WakeToRun` 自动唤醒电脑执行，执行完可继续睡眠* |
| 关机 | 下次开机登录时自动检测并补发 |

\* 需系统电源计划允许「唤醒计时器」（Windows 默认开启交流电唤醒）。

---

## 📁 项目结构

```
app/
├─ app_launcher.py        # 统一入口（无参数=GUI / --run=执行任务）
├─ gui_qt.py              # PyQt5 设置面板
├─ main.py                # 主流程：智能调度（完成即退 / 未到点等待 / 错过补发）
├─ config.yaml            # 用户配置
├─ diag.py                # 页面结构诊断工具
├─ modules/
│  ├─ sender.py           # 消息面板导航、好友定位（滚动查找/搜索）、发送与确认
│  ├─ login.py            # 登录态管理（sessionid 检测、扫码等待）
│  ├─ state.py            # 每日一次防重记录（原子写入）
│  └─ logger.py           # 按天滚动的运行日志
└─ scripts/
   ├─ install.bat         # 开发环境一键安装
   ├─ start_gui.bat       # 启动面板
   ├─ run_now.bat         # 手动执行一次
   └─ register_task.ps1   # 注册/删除 Windows 定时任务与登录自启
```

---

## ❓ 常见问题

<details>
<summary><b>提示找不到好友？</b></summary>

确认三点：① config.yaml 中填写的是你对该好友的**备注名**且完全一致；② 你与对方有过私信记录（会话出现在消息列表）；③ 对方未注销/封禁账号。程序会先在会话列表全量滚动查找，再尝试面板内搜索，两者都失败才会报错。
</details>

<details>
<summary><b>电脑睡眠后还会准时发吗？</b></summary>

会。定时任务注册时已启用唤醒权限，到点自动唤醒电脑执行；若电脑已关机，则下次开机登录时自动补发当天任务。
</details>

<details>
<summary><b>发送时间是乱填的能识别吗？</b></summary>

可以。`9：5`、`9点5`、`930`、`２１` 等常见误输都会被自动纠正为标准格式后才保存，非法值（如 25:00）会被拒绝并提示。
</details>

<details>
<summary><b>有账号风险吗？</b></summary>

任何第三方自动化操作都存在违反平台协议的风险。本工具采用拟人化操作（随机延迟、逐字键入、低频单次），但无法承诺零风险，请自行评估并遵守平台规则。
</details>

<details>
<summary><b>我的账号信息安全吗？</b></summary>

登录态仅保存在本机 `data/profile` 目录，程序不含任何上传逻辑。请勿将该目录分享给他人（等同于交出登录凭证），也请勿将包含个人数据的目录打包外传。
</details>

---

## 🐛 反馈与支持

欢迎通过 [GitHub Issues](https://github.com/YHAz1/DY_SparkAutoKeeper/issues) 反馈：

- **Bug 反馈**：请附上运行日志 `logs/app.log` 的相关片段、复现步骤与预期行为
- **功能建议**：描述使用场景与期望效果即可
- **页面改版失效**：抖音网页前端更新可能导致元素定位失效，可运行诊断脚本并将输出一并提交：

```bat
conda run -n dy_spark python app\diag.py
```

> ⚠️ 提交 Issue 前**务必删除日志中的个人信息**（好友备注名等），切勿上传 `data/profile`、`data/state.json` 等含凭证/隐私的文件。

---

## ⚠️ 免责声明

> [!IMPORTANT]
> 在下载、复制或使用本软件之前，请仔细阅读以下条款。**一旦使用本软件即视为已阅读并同意全部条款。**

1. 本工具仅供个人学习与娱乐交流使用，请勿用于商业用途或任何违法违规用途；
2. 本工具为第三方自动化工具，与平台官方无任何关联，非官方产品；
3. 自动化操作可能违反平台用户协议及社区规范，存在账号被限制、封禁的风险；
4. 请遵守平台规则，合理低频使用；使用本工具产生的一切后果由使用者自行承担；
5. 登录态含账号凭证，请勿将 data/profile 目录分享给他人，以免账号信息泄露；
6. 本工具仅限开发者授权的人使用，禁止未经授权外传、复制或转赠；
7. 使用过程中如有问题，可向开发者反馈；开发者不对本工具的稳定性、可用性负责，也不对任何直接或间接损失承担责任；
8. 使用本工具即表示已阅读并同意以上全部条款。

---

## 📄 许可证

本项目**未采用任何开源许可证**，保留所有权利（All Rights Reserved）。未经开发者书面许可，禁止复制、修改、分发或二次发布。个人学习用途请在上述免责条款范围内使用。

<div align="center">

**如果这个项目对你有帮助，欢迎点一个 Star ⭐**

</div>

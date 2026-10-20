# 可验证的研究工具包 `.run` 原型

本目录只构建 `artifact_kind=tooling` 的 Python zipapp。它用于验证软件包构建、完整性检查、用户目录安装、版本切换和回退。**它不含训练完成的 K1 策略，不刷写机器人，不访问电机或厂商固件，也不是生产发行系统。**

运行环境为 Linux / POSIX 和 Python 3.10 及以上，仅使用标准库，不需要 `sudo`。源码和工具运行依赖另见项目文档。

## 构建与使用

从项目根执行，以下路径按实际工作目录替换：

```sh
python3 release/build_run.py --source /absolute/path/k1-soccer-lab --output /absolute/path/dist/k1-soccer-tooling-0.1.0.run --version 0.1.0
/absolute/path/dist/k1-soccer-tooling-0.1.0.run --verify
/absolute/path/dist/k1-soccer-tooling-0.1.0.run --install-root /absolute/user/writable/k1-soccer-tooling
/absolute/path/dist/k1-soccer-tooling-0.2.0.run --install-root /absolute/user/writable/k1-soccer-tooling
/absolute/path/dist/k1-soccer-tooling-0.2.0.run --rollback --install-root /absolute/user/writable/k1-soccer-tooling
```

第一次安装目录必须尚不存在。后续操作仅接受具有本项目标识的目录，已有非本项目目录（包括空目录）会被拒绝。安装根必须是绝对路径，路径组件中不能包含符号链接。

构建器只打包 `k1lab/`、`configs/`、`docs/`、`tools/`、`README.md` 以及顶层源码锁 `sources.lock.json`（也接受 `source-lock.json`、`upstream.lock.json`）。不收录 `release/`、`tests/`、仓库历史、缓存或下载的第三方仓库。符号链接和特殊文件会被拒绝；普通文件保留可执行与不可执行之分，不复制特殊权限位。

## 完整性与版本机制

包内有 `manifest.json` 和 `manifest.sha256`，每个文件列出大小和 SHA-256。验证同时检查引导程序、条目集合、重复 ZIP 项、非法路径和符号链接。安装时再次计算解压内容摘要，完整验证后才发布新版本目录。

**SHA-256 是完整性校验，不是发布者签名。** 恶意者可以同时替换程序与清单。这种可执行 zipapp 的 `--verify` 也由包自身的引导程序执行，因此它不能为一个来源不可信的 `.run` 提供信任根。正式发行还需要包外的可信签名验证、密钥管理、兼容性门禁及真实设备验收。

安装后目录结构是：

- `releases/0.1.0/`、`releases/0.2.0/`：完整版本及对应清单。
- `current`：指向当前版本的相对符号链接。
- `previous`：指向前一版本的相对符号链接。
- `.k1-soccer-lab-root.json`：安装根标识。
- `.install.lock`：由 `flock` 保护安装和回退，第二个并发操作立即失败。

每个链接通过 `os.replace` 单独原子替换，`current` 是最终提交点；两个链接不是一个跨文件的原子事务。安装先完成完整解压和校验，再变更链接；正常异常路径保留原 `current`。旧版本不会被自动删除。回退会再次校验两个版本，然后交换链接；再次回退会切回另一个版本。

版本目录按不可变内容使用。不要在版本中编辑源文件、写日志或生成字节码缓存；配置、日志与实验输出放在目录之外。运行 Python 模块时使用 `python3 -B` 或 `PYTHONDONTWRITEBYTECODE=1`。被修改或多出文件的版本会拒绝激活和回退；同一版本号内容不同也会被拒绝覆盖。

这套原型只实现同一用户控制的安装目录中的进程级互斥和正常失败回退。它不宣称抵御另一个拥有同一目录写权限的恶意进程，也不承诺断电后的跨链接事务恢复；软件版本切换不会自动重启正在运行的进程。

## 测试

从项目根运行：

```sh
python3 -m unittest discover -s tests -p test_release.py -v
```

测试通过真实子进程构建和执行 `.run`，覆盖安装、第二版本升级、回退、不可变版本、坏包、重复条目、路径遍历、符号链接、相对安装根、已有目录保护、并发锁和受损版本拒绝回退。

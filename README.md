# MDTermaddon

通过 GitHub Actions 编译适用于 [MDTerm](https://github.com/giturass/MDTerm) 的 Termux:API、Termux:Boot、Termux:Styling、Termux:Tasker 和 Termux:X11。应用 APK 均为 Release，使用与 MDTerm 的 `Release APK` 工作流相同的签名；X11 仅提供 `sharedUid` 版。

上游源码固定在 [sources.lock.json](sources.lock.json) 中的提交，保留原包名、SDK 配置、显示名称和功能。

| 插件 | 上游版本 | 安装包名 | 清单最低 Android / compileSdk |
| --- | --- | --- | --- |
| [Termux:API](https://github.com/termux/termux-api/tree/v0.53.0) | 0.53.0 | `com.termux.api` | 7.0 / 35 |
| [Termux:Boot](https://github.com/termux/termux-boot/tree/v0.8.1) | 0.8.1 | `com.termux.boot` | 5.0 / 34 |
| [Termux:Styling](https://github.com/termux/termux-styling/tree/v0.32.1) | 0.32.1 | `com.termux.styling` | 5.0 / 34 |
| [Termux:Tasker](https://github.com/termux/termux-tasker/tree/v0.9.0) | 0.9.0 | `com.termux.tasker` | 5.0 / 35 |
| [Termux:X11](https://github.com/termux/termux-x11/tree/fa3a8b430e2896a19f44c99a9cb056254615ae06) | 1.03.01 / `fa3a8b4` | `com.termux.x11` | 7.0 / 34 |

MDTerm 主程序包名为 `com.termux`，五个插件的 `sharedUserId` 均为 `com.termux`，targetSdk 均为 28。X11 的 `sharedUid` 版同时使用 `com.termux` 进程，通用 APK 包含 arm64-v8a、armeabi-v7a、x86、x86_64 四种架构的原生库；其他四个插件的 APK 不包含 JNI。它们面向 MDTerm 当前支持的 Android 12+、arm64-v8a 设备；表中的插件最低系统版本不会扩大 MDTerm 的支持范围。

包名已依据 MDTerm 当前提交 `2c2da4728ff68f00809fcf9c1fd510bd4abd7c6b` 的 [applicationId](https://github.com/giturass/MDTerm/blob/2c2da4728ff68f00809fcf9c1fd510bd4abd7c6b/app/build.gradle#L43) 和 [插件包名常量](https://github.com/giturass/MDTerm/blob/2c2da4728ff68f00809fcf9c1fd510bd4abd7c6b/termux-shared/src/main/java/com/termux/shared/termux/TermuxConstants.java#L352) 核对，无需重命名。

## 构建和下载

先按下节配置 MDTerm Release 签名 Secrets，再将本项目推送到自己的 GitHub 仓库并启用 Actions，然后打开 **Actions → Build MDTerm addons (Release)**。

| 触发方式 | 构建类型 | 下载位置 |
| --- | --- | --- |
| 分支 push | Release | 对应运行的 Artifacts |
| Run workflow | Release | 对应运行的 Artifacts |
| 推送 `v*` 标签 | Release | Artifacts 和 GitHub Release |
| pull request | 仅脚本检查，不构建 APK，不访问签名 Secrets | 无 APK 产物 |

每次 APK 构建分别编译五个插件。产物包括 APK、SHA-256 校验和、`build-info.json` 和源码压缩包。APK 文件名为：

```text
MDTerm-api-v0.53.0-release.apk
MDTerm-boot-v0.8.1-release.apk
MDTerm-styling-v0.32.1-release.apk
MDTerm-tasker-v0.9.0-release.apk
MDTerm-x11-v1.03.01-fa3a8b4-sharedUid-release.apk
```

X11 还会生成配套命令包 `termux-x11-nightly-1.03.01-0-all.deb` 和 `termux-x11-nightly-1.03.01-0-any.pkg.tar.xz`，分别供 apt 和 pacman 使用。X11 APK 内的 `versionName` 沿用上游的版本号、提交及构建日期；下载文件名使用固定的基础版本号和短提交。

上传前会校验包名、sharedUserId、SDK、不可调试属性和签名证书。X11 另校验共享进程及四种架构的 `libXlorie.so`，其他插件校验 APK 不含 JNI。

## 与 MDTerm 保持相同签名

在本仓库 **Settings → Secrets and variables → Actions** 中配置以下 Repository secrets，值必须与 MDTerm 的 [Release APK 工作流](https://github.com/giturass/MDTerm/blob/master/.github/workflows/release.yml) 构建所安装主程序时使用的值一致：

| Secret | 内容 |
| --- | --- |
| `MDTERM_RELEASE_KEYSTORE_BASE64` | 同一个签名密钥库的 Base64 内容 |
| `MDTERM_RELEASE_STORE_PASSWORD` | 密钥库密码 |
| `MDTERM_RELEASE_KEY_ALIAS` | 密钥别名 |
| `MDTERM_RELEASE_KEY_PASSWORD` | 私钥密码 |

仅 Secret 名称相同不代表签名相同。可额外设置 Repository variable `MDTERM_RELEASE_CERT_SHA256`，填写 MDTerm release 证书的 SHA-256 指纹，构建时再核对一次。密钥内容只放在 Actions Secrets 中。

安装时让主程序与所有插件使用同一签名。不匹配的签名会导致安装失败或插件无法共享主程序的权限。构建缺少任意一项必需的签名 Secret 时会直接失败。

## 使用插件

- **API**：安装 APK 后在 MDTerm 中执行 `pkg install termux-api`，按需启动插件并授予所需权限。
- **Boot**：安装后打开一次插件，在 MDTerm 的 `~/.termux/boot/` 下放置开机脚本。
- **Styling**：从 MDTerm 的终端菜单打开 `Style`，选择字体和配色；该插件沿用上游设计，没有独立启动器入口。
- **Tasker**：先启动 MDTerm 完成初始化，再安装插件。在 Android 设置中打开 Tasker 等插件宿主的应用权限，授予“在 Termux 环境中运行命令”（`com.termux.permission.RUN_COMMAND`）。在 MDTerm 中执行 `mkdir -p ~/.termux/tasker` 和 `chmod 700 ~/.termux/tasker`，将脚本放入该目录，在宿主的 Termux:Tasker 动作中填写脚本名。只有需要执行此目录外的命令时，才在 `~/.termux/termux.properties` 中设置 `allow-external-apps=true`；详见[上游配置说明](https://github.com/termux/termux-tasker/tree/v0.9.0#setup-instructions)。
- **X11**：安装本项目的 `sharedUid` Release APK，同时安装同一次构建产出的配套命令包。命令包中的 loader 会核对 X11 APK 的签名，因此需与本项目签名的 APK 配套使用。

MDTerm 默认 apt 环境下，下载同一次构建的 `.deb` 后，在文件所在目录执行：

```sh
pkg install x11-repo
apt install ./termux-x11-nightly-1.03.01-0-all.deb
apt-mark hold termux-x11-nightly
```

锁定该包可防止后续 `pkg upgrade` 用官方仓库的命令包替换它，造成签名不匹配。更新本项目的配套命令包前，先执行 `apt-mark unhold termux-x11-nightly`，安装新包后再锁定。使用 pacman 的环境可选择同一次构建的 `.pkg.tar.xz`。

安装桌面后即可启动，例如 `pkg install xfce`，然后执行 `termux-x11 :1 -xstartup "dbus-launch --exit-with-session xfce4-session"`。其他桌面和显示参数参见 [Termux:X11 使用说明](https://github.com/termux/termux-x11/tree/fa3a8b430e2896a19f44c99a9cb056254615ae06#running-graphical-applications)。

## 构建说明

Actions 使用 JDK 17 和上游 Gradle Wrapper，显式安装 SDK Build Tools 34.0.0 用于产物签名检查；编译所需其他版本由上游 AGP 自动安装。各插件工具链如下：

| 插件 | Gradle / AGP | 原生构建工具 |
| --- | --- | --- |
| API、Tasker | 8.9 / 8.7.3 | 无 |
| Boot、Styling | 8.5 / 8.3.2 | 无 |
| X11 | 9.8.0 / 9.3.1 | NDK 29.0.14206865、CMake 3.22.1、bison、patch |

API、Tasker 的上游 `termux-shared` 依赖使用短提交 `7bceab88e2`，对应 JitPack 地址目前返回 404。本项目将其展开为同一提交 `7bceab88e2272f961d1b94ef736f1a9e20173247`，其 [POM 和 AAR](https://jitpack.io/com/termux/termux-app/termux-shared/7bceab88e2272f961d1b94ef736f1a9e20173247/termux-shared-7bceab88e2272f961d1b94ef736f1a9e20173247.pom) 可正常获取，不切换依赖源码版本。两者沿用上游规则排除依赖中的 JNI，因此无需构建 NDK 库。

构建脚本面向安装了 JDK 17、Android SDK 并已检出固定上游源码的环境。建议直接使用 GitHub Actions；官方 Android SDK 的 Linux aapt2 不能直接在 Android Termux 中运行。

源码压缩包包含本次修改后的上游源码、许可证和构建脚本，递归包含 X11 子模块中的源码及许可证，排除 `.git`、缓存和签名密钥。归档前会校验子模块已初始化并与父仓库锁定的提交一致。

使用本项目脚本重新构建时，先检出本项目，再按 `sources.lock.json` 将所选插件检出到 `upstream/`，并通过环境变量提供上述四项签名配置。`upstream/` 必须直接是所选上游仓库的根目录；开发时用于检查源码的 `upstream/x11/`、`upstream/tasker/` 子目录不适用于 `build.sh`。例如，在尚无 `upstream/` 的本项目工作目录中构建 X11：

```sh
git clone https://github.com/termux/termux-x11.git upstream
git -C upstream checkout fa3a8b430e2896a19f44c99a9cb056254615ae06
git -C upstream submodule update --init --recursive
bash scripts/build.sh x11
```

构建脚本会验证 Git 提交，X11 应用只构建 `:lorie-app:assembleSharedUidRelease`，并另生成配套命令包。其他插件运行 `bash scripts/build.sh api`，将参数替换为 `boot`、`styling` 或 `tasker` 即可，始终生成 Release APK。

上游应用采用 GPLv3，第三方原生依赖遵循各自许可证，源码压缩包保留对应源码和许可证。SDK 与工具链依据：[AGP 8.7 兼容性](https://developer.android.com/build/releases/past-releases/agp-8-7-0-release-notes)、[AGP 8.3 兼容性](https://developer.android.com/build/releases/past-releases/agp-8-3-0-release-notes)、[锁定的 X11 构建配置](https://github.com/termux/termux-x11/tree/fa3a8b430e2896a19f44c99a9cb056254615ae06)。

# MDTermaddon

通过 GitHub Actions 编译适用于 [MDTerm](https://github.com/giturass/MDTerm) 的 Termux:API、Termux:Boot 和 Termux:Styling，仅生成 Release APK，使用与 MDTerm 的 `Release APK` 工作流相同的签名。

上游源码固定在 [sources.lock.json](sources.lock.json) 中的提交，保留原包名、SDK 配置、显示名称和功能。

| 插件 | 上游版本 | 安装包名 | 最低 Android / compileSdk |
| --- | --- | --- | --- |
| [Termux:API](https://github.com/termux/termux-api/tree/v0.53.0) | 0.53.0 | `com.termux.api` | 7.0 / 35 |
| [Termux:Boot](https://github.com/termux/termux-boot/tree/v0.8.1) | 0.8.1 | `com.termux.boot` | 5.0 / 34 |
| [Termux:Styling](https://github.com/termux/termux-styling/tree/v0.32.1) | 0.32.1 | `com.termux.styling` | 5.0 / 34 |

MDTerm 主程序包名为 `com.termux`，三个插件的 `sharedUserId` 均为 `com.termux`，targetSdk 均为 28。插件 APK 不包含 JNI，可用于 MDTerm 当前支持的 Android 12+、arm64-v8a 设备；插件自身较低的最低系统版本不会扩大 MDTerm 的支持范围。

包名已依据 MDTerm 当前提交 `2c2da4728ff68f00809fcf9c1fd510bd4abd7c6b` 的 [applicationId](https://github.com/giturass/MDTerm/blob/2c2da4728ff68f00809fcf9c1fd510bd4abd7c6b/app/build.gradle#L43) 和 [插件包名常量](https://github.com/giturass/MDTerm/blob/2c2da4728ff68f00809fcf9c1fd510bd4abd7c6b/termux-shared/src/main/java/com/termux/shared/termux/TermuxConstants.java#L352) 核对，无需重命名。

## 构建和下载

先按下节配置 MDTerm Release 签名 Secrets，再将本项目推送到自己的 GitHub 仓库并启用 Actions，然后打开 **Actions → Build MDTerm addons (Release)**。

| 触发方式 | 构建类型 | 下载位置 |
| --- | --- | --- |
| 分支 push | Release | 对应运行的 Artifacts |
| Run workflow | Release | 对应运行的 Artifacts |
| 推送 `v*` 标签 | Release | Artifacts 和 GitHub Release |
| pull request | 仅脚本检查，不构建 APK，不访问签名 Secrets | 无 APK 产物 |

每次 APK 构建分别编译三个插件。产物包括 APK、SHA-256 校验和、`build-info.json` 和源码压缩包。APK 文件名为：

```text
MDTerm-api-v0.53.0-release.apk
MDTerm-boot-v0.8.1-release.apk
MDTerm-styling-v0.32.1-release.apk
```

上传前会校验包名、sharedUserId、SDK、不可调试属性、签名证书及 APK 不含 JNI。

## 与 MDTerm 保持相同签名

在本仓库 **Settings → Secrets and variables → Actions** 中配置以下 Repository secrets，值必须与 MDTerm 的 `Release APK` 工作流构建所安装主程序时使用的值一致：

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

## 构建说明

Actions 使用 JDK 17 和上游 Gradle Wrapper。API 使用 Gradle 8.9 / AGP 8.7.3，Boot、Styling 使用 Gradle 8.5 / AGP 8.3.2，SDK Build Tools 为 34.0.0。

API 的上游 `termux-shared` 依赖使用短提交 `7bceab88e2`，对应 JitPack 地址目前返回 404。本项目将其展开为同一提交 `7bceab88e2272f961d1b94ef736f1a9e20173247`，其 [POM 和 AAR](https://jitpack.io/com/termux/termux-app/termux-shared/7bceab88e2272f961d1b94ef736f1a9e20173247/termux-shared-7bceab88e2272f961d1b94ef736f1a9e20173247.pom) 可正常获取，不切换依赖源码版本。API 沿用上游规则排除依赖中的 JNI，因此无需构建 NDK 库。

构建脚本面向安装了 JDK 17、Android SDK 并已检出固定上游源码的环境。建议直接使用 GitHub Actions；官方 Android SDK 的 Linux aapt2 不能直接在 Android Termux 中运行。

源码压缩包包含本次修改后的上游源码、许可证和构建脚本，不包含 `.git`。使用本项目脚本重新构建时，先从本项目仓库检出代码，再按 `sources.lock.json` 将所选插件的仓库和提交检出到 `upstream/`，并通过环境变量提供上述四项签名配置；脚本会验证 Git 提交。运行 `bash scripts/build.sh api`（将 `api` 替换为 `boot` 或 `styling` 可构建其他插件），始终生成 Release APK。

上游应用采用 GPLv3，源码压缩包保留对应源码和许可证。SDK 与工具链依据：[AGP 8.7 兼容性](https://developer.android.com/build/releases/past-releases/agp-8-7-0-release-notes)、[AGP 8.3 兼容性](https://developer.android.com/build/releases/past-releases/agp-8-3-0-release-notes)。

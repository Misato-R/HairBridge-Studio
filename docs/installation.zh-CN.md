# HairBridge Studio 安装与依赖说明

工作台的 Blender 构建依赖三个组件：Surface Hair Curve Tool、Stylized Hair PRO（SHP）和 HairBridge Studio。本项目已包含两个自编插件的源码及独立安装包；SHP 继续单独安装。

网页默认使用英文，顶部 **中文 / English** 可随时切换并记住选择。界面、生成任务提示词与项目包打开说明跟随语言；项目名、备注、文件路径和ID保留原值。英文操作指南见[English installation and workflow](installation.en.md)。Blender配套面板也提供独立语言选择，需安装此次更新的两个ZIP。

## 先下载哪两个包

- [Surface Hair Curve Tool 0.1.0](../installers/surface_hair_curve_tool.zip)：对应源码为 `addon/surface_hair_curve_tool/`，含 Python 模块和随插件使用的两个节点预设文件。
- [HairBridge Studio 0.1.1](../installers/hairbridge_studio.zip)：对应源码为 `addon/hairbridge_studio/`，含内置 HairDeck JSON Bridge。
- [版本与 SHA-256 清单](../installers/manifest.json)：记录两个安装包的版本、大小、文件数及校验值。

GitHub 上打开 ZIP 文件后使用 **Download raw** 下载，保留 `.zip` 后缀，不要下载网页。工作台网页中的“下载 Blender 插件”仍只提供 HairBridge Studio；首次安装还应从上述位置取得 Surface Hair。

## 当前 ZIP 包含什么

`dist/hairbridge_studio.zip` 是 Blender 安装包，目录内容如下：

```text
hairbridge_studio/
  __init__.py
  preview_export.py
  strand_edit.py
  hairdeck_bridge/
    __init__.py
    mapping.py
    frames.py
    HAIRDECK-LICENSE.txt
```

- **HairBridge Studio**：加载项目与参考网格、导线精修、截面调整、预览导出和返回审核副本。
- **内置 HairDeck JSON Bridge**：读取导线数据、拟合原生曲线、映射截面并连接 SHP。安装 HairBridge Studio 时自动注册这部分代码，不需要再安装历史的独立 `hairdeck_bridge.zip`。
- `frames.py` 包含已注明来源的 HairDeck 标架计算，并随附其许可文件。它不是 HairDeck 模型或权重。

| 组件 | 包内包含 | 当前完整构建是否需要 | 获取或使用方式 |
|---|---|---|---|
| HairBridge Studio 与内置桥接 | 是 | 是 | 从工作台下载，或从源码构建 ZIP |
| Surface Hair Curve Tool 0.1.0 | 单独 ZIP | 是 | 源码与 `installers/surface_hair_curve_tool.zip` 均已纳入项目 |
| Stylized Hair PRO 4.3.1 | 否 | 是 | 从[作者发布页](https://deanzarkov.gumroad.com/l/stylized_hair_pro)获取并单独安装 |
| HairMesh 1.1.1 | 否 | 否 | [GitHub 仓库](https://github.com/riel-gab/hairmesh)，[实验所用版本](https://github.com/riel-gab/hairmesh/releases/tag/v1.1.1)；仅复现该工具往返实验时需要 |
| Hair Curve Toolkit 0.24.18 | 否 | 否 | 作者晴天雨私人提供的实验工具；[作者功能介绍与演示](https://www.bilibili.com/video/BV1rqpe6sEVU/)，不是用户安装前提 |
| HairDeck 模型及环境 | 否 | 仅本地 HairDeck 生成分支需要 | 按[官方仓库](https://github.com/hyz317/HairDeck)配置，导线导入和 Blender 构建不要求调用该模型 |
| Tripo Studio | 否 | 生成 Tripo 粗模时需要 | 使用自己的已登录服务；不会随插件安装 |

本机的 Surface Hair Curve Tool 和 SHP 位于 Blender 5.2 用户目录。既有桥接代码能查找同主版本的较早用户目录，所以 Blender 5.3 的历史检查也能够使用它们。新机器应当在实际使用的 Blender 配置中安装和启用依赖，不依赖这台机器的旧目录。

## Blender 安装顺序

先准备上述两个 ZIP，以及从 [SHP 作者发布页](https://deanzarkov.gumroad.com/l/stylized_hair_pro)获取的 SHP 4.3.1 安装包。老师进行作业验证时可使用单独提供的教师附件，见[教师验证说明](teacher-verification.zh-CN.md)。

1. 使用 Blender 5.3.0 复现已有检查。HairBridge Studio 声明的最低版本为5.2；目前没有在每个满足版本号的 Blender 环境中逐一验收。
2. 在 Blender 中打开 **Edit → Preferences → Add-ons**，从右上菜单选择 **Install from Disk**。
3. 选择 `surface_hair_curve_tool.zip`，安装并启用 **Surface Hair Curve Tool 0.1.0**。它与 HairBridge 是两个独立插件，安装一个不会自动安装另一个。
4. 用同样方式安装并启用 **Stylized Hair PRO**，使用与目标 Blender 版本匹配的作者发布包。既有检查使用4.3.1。
5. 安装并启用 **HairBridge Studio**：选择 `hairbridge_studio.zip`。三个插件均直接选择 ZIP 安装，无需解压后逐个选择 Python 文件。
6. 保存首选项。若已有历史独立桥接版本，优先使用新的工作台插件；不要为了新安装再额外添加旧的 `hairdeck_bridge.zip`。
7. 在3D视图按 **N**，查看 **HairBridge** 面板。面板出现只表明界面已加载，仍需用一个项目完成下面的功能检查。

[Blender 官方安装说明](https://docs.blender.org/manual/en/5.0/editors/preferences/extensions.html)介绍从磁盘安装扩展和旧式插件的入口；不同语言界面的菜单名称可能不同。

## 工作台运行与项目载入

1. 安装 Node.js 22或更新版本，在项目目录运行 `npm start`，或在 Windows 双击 `Start_HairBridge.bat`。
2. 首次运行先将 `local-config.example.json` 复制为 `local-config.json`，把 `blender` 改为自己的 Blender 可执行文件路径；需要 HairDeck 分支时再配置其模型目录、工作目录和 Python 环境。修改配置后重启服务。打开服务显示的本机地址，默认是 `http://127.0.0.1:8787`。
3. 从工作台获得导线数据后生成 Blender 工程，或在 **HairBridge → 载入工作台项目** 选择 `project.hairbridge`。项目清单需要与相邻的 `assets` 文件夹保留在一起。
4. 检查导线、SHP 几何和参考网格。尝试一次局部编辑和撤销，确认对应发束响应，再将审核副本返回工作台。

后台 Blender 使用配置的可执行文件和其插件环境。用户在另一个 Blender 版本中安装成功，不代表后台使用的那个版本已经具备依赖。

如果缺少依赖，现有加载逻辑会提示启用 `surface_hair_curve_tool` 或 `stylized_hair_pro`。看到网页上的“Blender 可用”或看到 HairBridge 面板，都不能替代实际构建检查。

## 从源码构建工作台插件

在项目根目录运行：

```powershell
python scripts/package_addon.py
```

它分别打包 `addon/hairbridge_studio/` 和 `addon/surface_hair_curve_tool/`，在 `installers/` 生成两个独立 ZIP 和校验清单，并将 ZIP 同步到 `dist/` 供工作台下载。脚本只读取这两个项目内的源码目录，不会收集电脑上安装的 SHP 或其他插件，也不会将两个插件合并成一个安装包。

网页的“下载 Blender 插件”由 `/api/addon` 提供，返回这个现有 ZIP。修改 `addon/` 源码后应重新执行打包，网页不会自动重建 ZIP。

`dist/` 被 `.gitignore` 排除；`installers/` 未排除，两个安装包会随项目源码一起提交，也可附在 GitHub Release 中。修改源码后必须运行上面的命令，使源码、安装包和清单保持一致。从工作台导出的项目包保存项目素材与记录，不代替插件安装。

## 当前已核对与仍待完成

- 自编 Surface Hair 源码和节点预设已从作者的现有安装副本整理到项目内，保留作者及 Codex 协助署名；对应独立 ZIP 已可从项目源码重建。
- SHP 不进入这两个公开安装包。教师附件与公开仓库分开，保留 SHP 原始版权及 MIT 许可，说明本次提供的评分用途。
- 最新安装包已在独立临时配置中完成安装与基本构建检查；选定样例的导线重做、实际构建及最终确认另有项目记录。不同试跑的完成范围见[提交验证整理](submission-validation.zh-CN.md)与[安装验证记录](validation.md)，不据此推断跨发型适用性或编辑效率。

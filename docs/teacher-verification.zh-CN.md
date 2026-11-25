# 教师验证附件说明

公开仓库包含项目源码、Surface Hair Curve Tool 和 HairBridge Studio 的安装包。SHP 是 Dean Zarkov 的付费产品，也是本项目将导线转换为可编辑几何的必要工具；不放入公开仓库和公开安装包。

## 单独交给老师的材料

本地 `teacher-verification/` 已由 `.gitignore` 排除。提交作业时单独附上其中的 `A2_Teacher_Verification.zip`，通过课程提交入口交给评分教师，不放到 GitHub 或公开下载链接。附件包含：

- `surface_hair_curve_tool.zip`：本项目自编曲线插件。
- `hairbridge_studio.zip`：工作台配套插件，内含 JSON Bridge。
- `stylized_hair_pro-4.3.1.zip`：从本机现有安装目录重建的 SHP 扩展包，保留原作者所有源文件、资产、README、清单及许可证；它不是声称从商店取得的原始 ZIP。
- `TEACHER_README.md`：中英文安装步骤、评分用途说明和验证边界。
- `checksums.json`：三个 ZIP 的版本、大小与 SHA-256。

整个 `A2_Teacher_Verification.zip` 是材料集合，先解压一次；里面三个插件 ZIP 应直接从 Blender 的 **Install from Disk** 安装，不再逐个解压。

## 附件中的用途说明

> Stylized Hair PRO 由 Dean Zarkov 开发，是单独销售的第三方工具，也是本项目运行所需的依赖。本附件仅为方便本次课程作业评分与功能验证而提供。请仅用于本次评阅，不转传、不公开上传，也不将本附件用于商业项目；如需继续使用，请支持原作者并从官方渠道获取。插件版权及原始许可保留归原作者。

**许可说明需要与使用请求区分。** 本机 SHP 4.3.1 的 `blender_manifest.toml` 标为 `SPDX:MIT`，README 和 `LICENSE.txt` 亦声明 MIT。该许可并没有禁止分享或商业使用。因此上文是本次附件的使用请求，不是原作者禁止分享、禁止商用的许可条款，也不替代或收窄包内的 MIT 许可。公开说明链接至[作者产品页](https://deanzarkov.gumroad.com/l/stylized_hair_pro)，本次重建附件完整保留原始版权和许可文件。

## 前期实验工具：演示与来源

下面两个工具用于开发阶段的对照实验，不是最终原型的运行依赖，教师验证附件不包含它们的插件文件。

- **Hair Curve Toolkit**：作者署名为 bilibili 晴天雨，本项目实验使用0.24.18，由作者私人提供。公开操作参考：[《Blender 曲线毛发插件功能介绍与演示》](https://www.bilibili.com/video/BV1rqpe6sEVU/)。本项目用它比较固定导线下的截面效果；视频用于了解工具操作，实验版本以本地记录为准。视频链接由学生提供，保留原作者与平台来源，不转载视频或私人插件文件。
- **HairMesh**：作者／维护者 riel-gab，[GitHub 仓库](https://github.com/riel-gab/hairmesh)；本项目使用 [1.1.1 版本](https://github.com/riel-gab/hairmesh/releases/tag/v1.1.1)。用于导线导入、锚点编辑、导出及回写 SHP 的往返检查。仓库及发布页供来源查询或按需复现实验，老师运行最终原型无需额外安装。

## 安装与验证

使用 Blender 5.3.0 复现本项目检查。按 **Surface Hair Curve Tool → SHP 4.3.1 → HairBridge Studio** 顺序安装并启用；SHP 4.3.1 的清单要求 Blender 5.2 或更新版本。完整步骤见[安装指南](installation.zh-CN.md)。

运行工作台需要 Node.js 22 或更新版本。HairDeck 的本地推理分支另外需要其模型、Python 环境及权重；这些不在教师附件内。已有导线的导入与 Blender 构建不要求运行 HairDeck。Tripo 生成也需要使用者自己的服务会话。

可复现的七束样例在公开仓库中。按 README 运行 `npm run example` 和 `npm start` 后，打开样例命令输出的地址。老师可以查看已有导线，也可以安装附件里的依赖后重新构建。原试跑的构建结果和验收信息见验证记录。[样例入口](../README.md#try-the-supplied-test-materials) · [验证记录](validation.md)

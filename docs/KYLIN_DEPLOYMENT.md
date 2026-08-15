# KylinStock 银河麒麟 V10 / 飞腾 ARM64 部署与验证指南

> 目标设备：银河麒麟桌面操作系统 V10 JICAI / UKUI / Phytium D2000 / ARM64 / 16GB RAM

## 1. 交付目标

最终用户体验：

`麒麟桌面 -> 双击“物资管理系统” -> KylinStock 独立桌面窗口 -> 本地 SQLite 数据库`

第一阶段不要求开机自启动，不依赖互联网，不要求用户手动启动数据库或后台服务。

## 2. 交付原则

1. 最终生产包必须经过目标银河麒麟设备实机验证；
2. GitHub Actions 的 Ubuntu ARM64 构建只作为原生 ARM64 编译/打包烟测，不能替代银河麒麟兼容性验收；
3. 不允许为了安装软件破坏客户机器现有系统库；
4. 如银河麒麟系统 WebKitGTK/GTK/GLIBC 与 CI 构建环境存在 ABI 差异，应调整构建环境或在兼容环境重新构建，不直接强行升级客户核心系统库；
5. 首次安装前应保留系统环境诊断记录。

## 3. 第一次到目标机后的环境诊断

在仓库根目录执行：

```bash
chmod +x scripts/kylin-doctor.sh
./scripts/kylin-doctor.sh | tee kylin-stock-doctor.txt
```

重点记录：

- `uname -m` / CPU 架构；
- 银河麒麟发行版信息；
- GLIBC 版本；
- WebKitGTK 4.1 / 4.0 情况；
- GTK3；
- OpenSSL；
- 桌面会话与语言环境；
- 如需目标机本机构建，则额外确认 Node.js、Rust、gcc、make、dpkg-deb。

诊断输出保存在项目验收记录中。

## 4. CI ARM64 烟测

GitHub Actions 使用原生 `ubuntu-22.04-arm` runner：

- 确认 runner `uname -m = aarch64`；
- 安装 Tauri Linux 构建依赖；
- 安装前端依赖；
- 执行 Tauri ARM64 `.deb` 构建；
- 使用 `dpkg-deb --info` 检查生成包；
- 上传短期保存的 smoke artifact。

该产物的意义是：验证 KylinStock 的 Rust/Tauri/Node 依赖能够在 Linux ARM64 上原生编译和打包。

**该 CI 产物不是默认的客户正式交付包。** 银河麒麟 V10 目标机可能具有不同的 GLIBC、WebKitGTK、GTK 和系统库版本，最终包仍需通过目标机实测。

## 5. 真机安装验收

正式候选包在客户机上至少验证：

1. 安装过程无破坏性系统依赖替换；
2. UKUI 应用菜单/桌面入口正常；
3. 双击可打开独立 KylinStock 窗口；
4. 中文字体和中文输入法正常；
5. 新增品名；
6. 入库；
7. 当前库存同步增加；
8. 出库并填写去向；
9. 库存不足时阻止出库；
10. 出入库流水正确；
11. 名称/时间/单位/去向组合查询；
12. XLSX 导出与麒麟上的办公软件兼容；
13. 即时备份；
14. 年度备份；
15. 数据恢复；
16. U 盘/移动介质目标路径可备份；
17. 软件关闭再启动数据仍存在；
18. 电脑重启后数据仍存在；
19. 多次连续入库/出库后库存与流水保持一致；
20. 卸载/升级流程不得误删业务数据库，除非用户明确执行数据清理。

## 6. 数据目录

Tauri SQL 的相对 SQLite 数据库 `sqlite:kylin-stock.db` 位于应用 `app_config_dir` 下。KylinStock 的原生库存事务与备份/恢复模块使用同一目录定位业务数据库。

现场不得根据猜测手工移动数据库。需要迁移数据时优先使用系统提供的“备份与恢复”功能。

## 7. 数据安全验收

### 入库事务

`BEGIN IMMEDIATE -> 写入入库流水 -> 增加库存 -> COMMIT`

### 出库事务

`BEGIN IMMEDIATE -> 检查库存 -> 写入出库流水 -> 条件扣减库存 -> COMMIT`

任何中间错误必须回滚。

### 恢复流程

`关闭数据库连接 -> 恢复前安全副本 -> 临时恢复文件 -> 文件替换 -> 重新打开数据库 -> integrity_check`

恢复失败时应优先回退到恢复前安全副本。

## 8. 发布候选包命名建议

正式交付时使用清晰版本和架构标识，例如：

```text
KylinStock_0.1.0_KylinV10_arm64.deb
```

测试构建必须带有 `smoke` / `test` 标识，避免被误当成正式交付版本。

## 9. 最终发布门槛

只有同时满足以下条件，才标记为客户正式 Release：

- x64 Linux CI build-check 通过；
- ARM64 Linux native build/package smoke 通过；
- 银河麒麟 V10 + 飞腾 D2000 实机安装通过；
- 核心出入库闭环通过；
- 查询/导出通过；
- 备份/恢复通过；
- 关闭与重启数据持久化通过；
- 客户需求文档中的验收项完成。

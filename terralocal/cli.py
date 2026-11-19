"""Composable project-local CLI and Windows launcher."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from terralocal import __version__
from terralocal.config import load_settings
from terralocal.server.domain.errors import DomainError


def output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main() -> int:
    parser = argparse.ArgumentParser(prog="terralocal", description="TerraLocal 本地兼容服务器与存档工具")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--data-dir", type=Path, help="存档与资源目录（默认 EXE 同级 data）")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("serve", help="启动游戏和管理服务；Ctrl+C 安全停止")
    commands.add_parser("launcher", help="打开 Windows 启动窗口")
    commands.add_parser("doctor", help="只读检查启动端口、存档和静态数据，输出 JSON")
    dp = commands.add_parser("gamedata", help="导入和比较静态游戏表")
    dc = dp.add_subparsers(dest="data_command", required=True)
    importer = dc.add_parser("import", help="校验并冻结解码后的 excel 表")
    importer.add_argument("folder", type=Path)
    importer.add_argument("--activate", action="store_true", help="用于下一次启动；保留旧版本缓存")
    differ = dc.add_parser("diff")
    differ.add_argument("left", help="已导入数据哈希")
    differ.add_argument("right", help="已导入数据哈希")
    drops = commands.add_parser("drops", help="离线编译、校验及导入版本化掉落规则")
    drop_commands = drops.add_subparsers(dest="drop_command", required=True)
    compiler = drop_commands.add_parser("compile-penguin", help="将已下载的国服组合统计与匹配 GameData 比较")
    compiler.add_argument("patterns", type=Path)
    compiler.add_argument("stages", type=Path)
    compiler.add_argument("--out", type=Path, required=True, help="输出规则和相邻的编译报告；不激活")
    compiler.add_argument("--mode", choices=("official-like", "guaranteed", "custom", "debug"),
                          default="official-like")
    drop_importer = drop_commands.add_parser("import", help="校验并保存规则，服务重启后启用")
    drop_importer.add_argument("file", type=Path)
    drop_importer.add_argument("--dry-run", action="store_true", help="只校验，不修改激活文件或存档")
    drop_show = drop_commands.add_parser("show", help="显示当前掉落目录或某一关卡的规则")
    drop_show.add_argument("stage", nargs="?")
    drop_commands.add_parser("modes", help="说明四种掉落模式及本地策略边界")
    skinshop = commands.add_parser("skinshop", help="校验、导入和查看版本绑定的普通服装销售目录")
    skin_commands = skinshop.add_subparsers(dest="skin_command", required=True)
    skin_import = skin_commands.add_parser("import", help="校验并保存目录，保留旧版本；重启服务后生效")
    skin_import.add_argument("file", type=Path)
    skin_import.add_argument("--dry-run", action="store_true", help="只校验，不激活目录或修改存档")
    skin_commands.add_parser("show", help="显示当前目录的范围、来源模式及指纹")
    voucher = commands.add_parser("shop", help="导入和查看版本绑定的凭证商店目录")
    voucher_commands = voucher.add_subparsers(dest="shop_command", required=True)
    voucher_import = voucher_commands.add_parser("import", help="校验并保存目录和快照；服务重启后生效")
    voucher_import.add_argument("file", type=Path)
    voucher_import.add_argument("--dry-run", action="store_true", help="只校验，不修改目录或存档")
    voucher_commands.add_parser("show", help="显示当前目录的商店、周期、模式和指纹")
    cash = commands.add_parser("cashshop", help="导入和查看本地虚拟源石目录")
    cash_commands = cash.add_subparsers(dest="cash_command", required=True)
    cash_import = cash_commands.add_parser("import", help="核对 SDK 商品并保存目录；重启后生效")
    cash_import.add_argument("file", type=Path)
    cash_import.add_argument("--dry-run", action="store_true", help="只校验，不修改目录或存档")
    cash_commands.add_parser("show", help="显示源石目录来源、供给和指纹")
    packs = commands.add_parser("giftpacks", help="导入和查看版本绑定的组合包目录")
    pack_commands = packs.add_subparsers(dest="pack_command", required=True)
    pack_import = pack_commands.add_parser("import", help="核对 GameData、SDK 和周期并保留目录快照")
    pack_import.add_argument("file", type=Path)
    pack_import.add_argument("--dry-run", action="store_true", help="只校验，不激活或修改存档")
    pack_commands.add_parser("show", help="显示目录来源、范围及未完成类别")
    commands.add_parser("backup", help="备份现有 SQLite 存档并写入校验指纹")
    restore = commands.add_parser("restore", help="恢复经过校验的备份；先保留当前存档")
    restore.add_argument("name", help="backups 目录内的 .sqlite3 文件名")
    restore.add_argument("--output", type=Path, help="将备份恢复为新 .sqlite3 文件，原存档保持原样")
    pw = commands.add_parser("admin-password", help="设置管理密码，输入不会显示")
    pw.add_argument("--clear", action="store_true")
    arguments = sys.argv[1:]
    if getattr(sys, "frozen", False) and len(arguments) == 1 and Path(arguments[0]).is_absolute():
        # Explorer passes a folder dropped onto the EXE as a single absolute argument.
        folder = Path(arguments[0])
        if not folder.is_dir() or not any((folder / name).is_file() for name in ("settings.json", "terralocal.sqlite3")):
            parser.error("请选择含 settings.json 或 terralocal.sqlite3 的 TerraLocal 存档目录")
        arguments = ["--data-dir", str(folder)]
    args = parser.parse_args(arguments)
    if args.command == "doctor":
        from terralocal.server.services.doctor import diagnose

        report, exit_code = diagnose(args.data_dir)
        output(report)
        return exit_code
    try:
        settings = load_settings(args.data_dir)
        if args.command == "backup":
            from terralocal.server.services.backups import backup_existing_save

            output(backup_existing_save(settings))
            return 0
        if args.command == "restore" and args.output is not None:
            from terralocal.server.services.backups import recover_backup

            output(recover_backup(settings, args.name, args.output))
            return 0
        settings.prepare()
        if args.command is None:
            if getattr(sys, "frozen", False):
                from terralocal.launcher.window import launch

                launch(settings)
            else:
                parser.print_help()
            return 0
        if args.command == "gamedata":
            from terralocal.server.gamedata.repository import GameData, diff_data, import_data

            if args.data_command == "import":
                manifest = import_data(args.folder, settings.data_dir / "cache")
                if args.activate:
                    settings.gamedata_hash = manifest["hash"]
                    settings.save()
                output(manifest)
            else:
                for value in (args.left, args.right):
                    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                        raise ValueError("参数必须是 64 位已导入 GameData 哈希")
                output(diff_data(GameData(settings.data_dir / "cache" / args.left),
                                 GameData(settings.data_dir / "cache" / args.right)))
            return 0
        if args.command == "admin-password":
            import getpass

            from terralocal.server.domain.accounts import PASSWORDS

            if args.clear:
                if settings.admin_host != "127.0.0.1":
                    raise ValueError("管理端开放 LAN 时不可清除密码")
                settings.admin_password_hash = None
            else:
                password = getpass.getpass("新管理密码: ")
                if len(password) < 12 or password != getpass.getpass("再输入一次: "):
                    raise ValueError("密码至少 12 字符且两次输入必须一致")
                settings.admin_password_hash = PASSWORDS.hash(password)
            settings.save()
            output({"saved": True})
            return 0
        if args.command == "drops":
            from terralocal.server.gamedata import GameData
            from terralocal.server.gamedata.drops import atomic_write, read_catalog, write_catalog
            from terralocal.server.gamedata.repository import canonical

            if args.drop_command == "modes":
                output({"official-like": "根据完整样本的组合频次抽选；家具身份使用标记的本地策略",
                        "guaranteed": "每次发放 guaranteed_rewards；编译默认值取样本中每物品最小数量",
                        "custom": "每次发放 custom_rewards；可编辑目录并重新校验导入",
                        "debug": "每次发放 debug_rewards；编译默认值取每物品最大数量，组合可能未实际出现",
                        "first_pass": "GameData 缺少数量时默认 1，属于本地配置，可在目录中明确调整"})
                return 0
            if not settings.gamedata_hash:
                raise ValueError("请先导入并选择匹配的 GameData")
            data = GameData(settings.data_dir / "cache" / settings.gamedata_hash)
            data.verify()
            if args.drop_command == "compile-penguin":
                from terralocal.server.gamedata.penguin import compile_penguin

                if args.out.exists() or args.out.with_suffix(".report.json").exists():
                    raise ValueError("输出文件已存在，请选择新文件名以保留现有规则")
                catalog, report = compile_penguin(args.patterns, args.stages, data, mode=args.mode)
                args.out.parent.mkdir(parents=True, exist_ok=True)
                report_path = args.out.with_suffix(".report.json")
                atomic_write(report_path, canonical(report))
                atomic_write(args.out, canonical(catalog.model_dump()))
                output({**catalog.summary(), "out": args.out.resolve(), "report": report_path.resolve(),
                        "excluded_stages": len(report["excluded_stages"]),
                        "excluded_reasons": report["excluded_reasons"], "activated": False})
            elif args.drop_command == "import":
                catalog = read_catalog(args.file, data)
                snapshot = None if args.dry_run else write_catalog(catalog, settings.data_dir)
                output({**catalog.summary(), "dry_run": args.dry_run, "snapshot": snapshot,
                        "restart_required": not args.dry_run})
            else:
                catalog = read_catalog(settings.data_dir / "drop_rules.json", data)
                result = catalog.summary()
                if args.stage:
                    if args.stage not in catalog.stages:
                        raise ValueError("该关卡没有已导入的掉落规则")
                    result.update(stage_id=args.stage, rule=catalog.stages[args.stage].model_dump())
                output(result)
            return 0
        if args.command in {"serve", "launcher"}:
            settings.save()
            if args.command == "serve":
                from terralocal.launcher.service import serve

                serve(settings)
            else:
                from terralocal.launcher.window import launch

                launch(settings)
            return 0
        if args.command in {"skinshop", "shop", "cashshop", "giftpacks"}:
            from terralocal.server.compatibility.profile import native_profile
            from terralocal.server.gamedata import GameData
            if args.command == "skinshop":
                from terralocal.server.gamedata.skin_shop import read_catalog, write_catalog

                operation, filename = args.skin_command, "skin_shop.json"
            elif args.command == "cashshop":
                from terralocal.server.gamedata.cash_shop import frozen_products, read_catalog, write_catalog

                operation, filename = args.cash_command, "cash_shop.json"
            elif args.command == "giftpacks":
                from terralocal.server.gamedata.cash_shop import frozen_products
                from terralocal.server.gamedata.gift_packs import (
                    preflight_saved_catalog,
                    read_catalog,
                    write_catalog,
                )

                operation, filename = args.pack_command, "gift_packs.json"
            else:
                from terralocal.server.gamedata.voucher_shop import (
                    preflight_saved_catalog,
                    read_catalog,
                    write_catalog,
                )

                operation, filename = args.shop_command, "voucher_shop.json"

            if not settings.gamedata_hash:
                raise ValueError("请先导入并选择匹配的 GameData")
            data = GameData(settings.data_dir / "cache" / settings.gamedata_hash)
            data.verify()
            path = args.file if operation == "import" else settings.data_dir / filename
            catalog = (read_catalog(path, data, native_profile(settings.client_profile), *frozen_products(settings))
                       if args.command in {"cashshop", "giftpacks"}
                       else read_catalog(path, data, native_profile(settings.client_profile)))
            if args.command in {"shop", "giftpacks"}:
                preflight_saved_catalog(catalog, settings.database_path)
            result = catalog.summary()
            if operation == "import":
                saved = None if args.dry_run else write_catalog(catalog, settings.data_dir)
                result.update(dry_run=args.dry_run, snapshot=saved, restart_required=not args.dry_run)
            output(result)
            return 0
        from terralocal.server.services.backups import restore_existing_save

        output(restore_existing_save(settings, args.name))
        return 0
    except (ValueError, OSError, DomainError) as exc:
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            errors = [{"field": ".".join(map(str, e["loc"])), "type": e["type"]}
                      for e in exc.errors(include_input=False, include_context=False)[:12]]
            print(f"TerraLocal: 规则格式无效 {json.dumps(errors, ensure_ascii=False)}", file=sys.stderr)
        elif isinstance(exc, DomainError):
            print(f"TerraLocal: {exc.message}", file=sys.stderr)
        else:
            print(f"TerraLocal: {exc}", file=sys.stderr)
        return 2

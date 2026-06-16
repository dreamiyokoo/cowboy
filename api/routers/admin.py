from fastapi import APIRouter, Depends, HTTPException, status, Header
from fastapi.responses import FileResponse
from pathlib import Path
import os
import re
import shutil
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_db

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


async def verify_admin(x_admin_password: str = Header(None, alias="X-Admin-Password")):
    """ヘッダー X-Admin-Password の値を検証する依存関係"""
    if not x_admin_password or x_admin_password != settings.ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin password"
        )
    return True


@router.post("/login")
async def admin_login(x_admin_password: str = Header(None, alias="X-Admin-Password")):
    """管理パスワードの検証"""
    if not x_admin_password or x_admin_password != settings.ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin password"
        )
    return {"status": "ok"}


def _is_error_log_file(path: Path) -> bool:
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            text = f.read(32768)
        return bool(re.search(r"\[ERROR\]|result\s*[:=]\s*['\"]error['\"]|\berror\b", text, re.IGNORECASE))
    except Exception:
        return False


@router.get("/logs")
async def list_admin_logs(
    _ : bool = Depends(verify_admin)
):
    """/app/logs 内のログファイル一覧をタイムスタンプ逆順で取得"""
    log_dir = Path("/app/logs")
    if not log_dir.exists():
        return {"logs": []}
    
    logs = []
    try:
        for p in log_dir.glob("*.log"):
            if p.is_file():
                stat = p.stat()
                logs.append({
                    "filename": p.name,
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                    "isErrorLog": _is_error_log_file(p),
                })
        # 更新時間 (mtime) の降順 (最新順)
        logs.sort(key=lambda x: x["mtime"], reverse=True)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to scan logs: {e}"
        )
    return {"logs": logs}


@router.get("/logs/{filename}")
async def get_admin_log(
    filename: str,
    _ : bool = Depends(verify_admin)
):
    """管理用の特定ラウンドログファイル配信"""
    safe_name = Path(filename).name
    log_path = Path("/app/logs") / safe_name
    if not log_path.exists() or not log_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Log file not found"
        )
    return FileResponse(log_path, media_type="text/plain")


@router.delete("/games/reset")
async def reset_games(
    db: AsyncSession = Depends(get_db),
    _ : bool = Depends(verify_admin)
):
    """ゲーム履歴とログの全リセット"""
    # 1. データベースの games テーブルを TRUNCATE する
    try:
        await db.execute(text("TRUNCATE TABLE games RESTART IDENTITY CASCADE"))
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database reset failed: {e}"
        )

    # 2. ログディレクトリ内の全ログファイルを削除する
    log_dir = Path("/app/logs")
    if log_dir.exists() and log_dir.is_dir():
        try:
            for p in log_dir.glob("*.log"):
                if p.is_file():
                    p.unlink(missing_ok=True)
        except Exception as e:
            # ログ削除失敗はデータベースクリアが成功していれば警告に留めるが、APIとしてはエラーを返す
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"DB reset succeeded, but log deletion failed: {e}"
            )
            
    return {"status": "ok", "message": "Database and logs have been completely reset"}

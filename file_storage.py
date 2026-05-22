"""Сохранение вложений ДЗ: диск (локально) или Postgres (Vercel)."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from config import config
from database import HomeworkFile


async def save_homework_file(
    db: Session,
    hw_id: int,
    upload: UploadFile,
) -> HomeworkFile:
    raw = await upload.read()
    if config.STORE_FILES_IN_DB:
        hf = HomeworkFile(
            hw_id=hw_id,
            filename=upload.filename or "file",
            filepath="db://",
            file_data=raw,
            content_type=upload.content_type or "application/octet-stream",
        )
    else:
        ext = Path(upload.filename or "").suffix
        fname = f"{uuid.uuid4()}{ext}"
        dest = config.UPLOADS_DIR / fname
        dest.write_bytes(raw)
        hf = HomeworkFile(
            hw_id=hw_id,
            filename=upload.filename or fname,
            filepath=str(dest),
            file_data=None,
            content_type=upload.content_type or "application/octet-stream",
        )
    db.add(hf)
    db.commit()
    db.refresh(hf)
    return hf


def file_download_response(hf: HomeworkFile) -> Response:
    if hf.file_data is not None:
        return Response(
            content=bytes(hf.file_data),
            media_type=hf.content_type or "application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{hf.filename}"',
            },
        )
    path = Path(hf.filepath or "")
    if not path.is_file():
        raise FileNotFoundError(hf.filepath)
    return FileResponse(path, filename=hf.filename)


def delete_homework_file(hf: HomeworkFile) -> None:
    if hf.file_data is None:
        p = Path(hf.filepath or "")
        if p.is_file():
            try:
                p.unlink()
            except OSError:
                pass

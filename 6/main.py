from fastapi import FastAPI, BackgroundTasks
import subprocess
import uuid
import re
import shutil
from pathlib import Path
from PIL import Image

app = FastAPI()

# =========================
# 存储目录
# =========================
BASE_DIR = Path("./downloads")
BASE_DIR.mkdir(exist_ok=True)

TASKS = {}


# =========================
# 排序规则（核心：防止乱序）
# =========================
def natural_key(path: Path):
    nums = re.findall(r"\d+", path.name)
    return int(nums[0]) if nums else path.name


# =========================
# 图片 → PDF（稳定版）
# =========================
def images_to_pdf(folder: Path, output_pdf: Path):
    files = list(folder.rglob("*.*"))

    images = [
        f for f in files
        if f.suffix.lower() in [".webp", ".jpg", ".jpeg", ".png"]
    ]

    if not images:
        raise Exception("no images found")

    # 🔥 关键：按数字排序
    images.sort(key=natural_key)

    pil_images = []

    for img_path in images:
        with Image.open(img_path) as img:
            pil_images.append(img.convert("RGB"))

    first, *rest = pil_images

    first.save(
        output_pdf,
        "PDF",
        resolution=100.0,
        save_all=True,
        append_images=rest
    )

    # 🔥 释放资源
    for img in pil_images:
        img.close()


# =========================
# 后台任务
# =========================
def run_task(task_id: str, comic_id: str, task_dir: Path):
    try:
        TASKS[task_id]["status"] = "running"

        # 1️⃣ 下载
        result = subprocess.run(
            ["jmcomic", comic_id],
            cwd=str(task_dir),
            capture_output=True,
            text=True,
            timeout=300
        )

        # 2️⃣ PDF 输出（唯一产物）
        pdf_path = BASE_DIR / f"{comic_id}.pdf"
        images_to_pdf(task_dir, pdf_path)

        # 3️⃣ 清理临时文件（关键优化）
        shutil.rmtree(task_dir, ignore_errors=True)

        # 4️⃣ 写回状态
        TASKS[task_id]["status"] = "done"
        TASKS[task_id]["pdf"] = str(pdf_path)
        TASKS[task_id]["stdout"] = result.stdout
        TASKS[task_id]["stderr"] = result.stderr

    except subprocess.TimeoutExpired:
        TASKS[task_id]["status"] = "timeout"
        TASKS[task_id]["error"] = "download timeout (300s)"

    except Exception as e:
        TASKS[task_id]["status"] = "error"
        TASKS[task_id]["error"] = str(e)


# =========================
# API
# =========================
@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/download")
def download(comic_id: str, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    task_dir = BASE_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    TASKS[task_id] = {
        "comic_id": comic_id,
        "status": "queued",
        "dir": str(task_dir)
    }

    background_tasks.add_task(run_task, task_id, comic_id, task_dir)

    return {
        "task_id": task_id,
        "status": "queued"
    }


@app.get("/status/{task_id}")
def status(task_id: str):
    return TASKS.get(task_id, {"error": "not found"})

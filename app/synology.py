from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import requests


class SynologyClient:
    def __init__(self) -> None:
        base = os.getenv("SYNOLOGY_URL", "").rstrip("/")
        if not base:
            raise RuntimeError("SYNOLOGY_URL is not set")
        self.webapi = os.getenv("SYNOLOGY_WEBAPI_URL", f"{base}/webapi").rstrip("/")
        self.account = os.getenv("SYNOLOGY_USER", "")
        self.password = os.getenv("SYNOLOGY_PASSWORD", "")
        self.verify = os.getenv("SYNOLOGY_VERIFY_TLS", "1") not in {"0", "false", "False"}
        self.sid = ""
        if not self.account or not self.password:
            raise RuntimeError("SYNOLOGY_USER and SYNOLOGY_PASSWORD are required")

    def _get(self, cgi: str, params: dict, stream: bool = False) -> requests.Response:
        response = requests.get(f"{self.webapi}/{cgi}", params=params, stream=stream, timeout=60, verify=self.verify)
        response.raise_for_status()
        return response

    def _json(self, cgi: str, params: dict) -> dict:
        payload = self._get(cgi, params).json()
        if not payload.get("success"):
            raise RuntimeError(f"Synology API error: {payload.get('error', payload)}")
        return payload["data"]

    def login(self) -> str:
        data = self._json(
            "auth.cgi",
            {
                "api": "SYNO.API.Auth",
                "version": "3",
                "method": "login",
                "account": self.account,
                "passwd": self.password,
                "session": "FileStation",
                "format": "sid",
            },
        )
        self.sid = data["sid"]
        return self.sid

    def list_folder(self, folder_path: str) -> list[dict]:
        sid = self.sid or self.login()
        for attempt in range(3):
            try:
                data = self._json(
                    "entry.cgi",
                    {
                        "api": "SYNO.FileStation.List",
                        "version": "2",
                        "method": "list",
                        "folder_path": folder_path,
                        "additional": json.dumps(["size", "time"]),
                        "_sid": sid,
                    },
                )
                return data.get("files", [])
            except (requests.RequestException, RuntimeError):
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)
        return []

    def create_folder(self, folder_path: str, name: str) -> dict:
        sid = self.sid or self.login()
        return self._json(
            "entry.cgi",
            {
                "api": "SYNO.FileStation.CreateFolder",
                "version": "2",
                "method": "create",
                "folder_path": folder_path,
                "name": name,
                "force_parent": "true",
                "_sid": sid,
            },
        )

    def copy(self, path: str, dest_folder_path: str, overwrite: bool = True) -> str:
        sid = self.sid or self.login()
        data = self._json(
            "entry.cgi",
            {
                "api": "SYNO.FileStation.CopyMove",
                "version": "3",
                "method": "start",
                "path": json.dumps([path]),
                "dest_folder_path": dest_folder_path,
                "overwrite": "true" if overwrite else "false",
                "remove_src": "false",
                "accurate_progress": "false",
                "_sid": sid,
            },
        )
        return data["taskid"]

    def copy_status(self, taskid: str) -> dict:
        sid = self.sid or self.login()
        return self._json(
            "entry.cgi",
            {
                "api": "SYNO.FileStation.CopyMove",
                "version": "3",
                "method": "status",
                "taskid": taskid,
                "_sid": sid,
            },
        )

    def wait_copy(self, taskid: str, timeout: int = 300) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            data = self.copy_status(taskid)
            if data.get("finished"):
                return
            time.sleep(0.5)
        raise TimeoutError(f"Synology copy task timed out: {taskid}")

    def rename(self, path: str, name: str) -> dict:
        sid = self.sid or self.login()
        return self._json(
            "entry.cgi",
            {
                "api": "SYNO.FileStation.Rename",
                "version": "2",
                "method": "rename",
                "path": path,
                "name": name,
                "_sid": sid,
            },
        )

    def walk(self, folder_path: str):
        folders = [folder_path]
        workers = max(1, int(os.getenv("SYNOLOGY_SCAN_WORKERS", "4")))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            while folders:
                next_folders = []
                for items in pool.map(self.list_folder, folders):
                    for item in items:
                        if item.get("isdir"):
                            next_folders.append(item["path"])
                        else:
                            yield item
                folders = next_folders

    def download(self, path: str):
        sid = self.sid or self.login()
        response = self._get(
            "entry.cgi",
            {
                "api": "SYNO.FileStation.Download",
                "version": "2",
                "method": "download",
                "path": path,
                "mode": "download",
                "_sid": sid,
            },
            stream=True,
        )
        if "application/json" in response.headers.get("Content-Type", ""):
            payload = response.json()
            if not payload.get("success"):
                raise RuntimeError(f"Synology download error: {payload.get('error', payload)}")
        for chunk in response.iter_content(1024 * 1024):
            if chunk:
                yield chunk

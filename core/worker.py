#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多线程任务 Worker（xjyxjyw.com 专版）

Worker 流程:
  查询: 1.登录 → 2.获取分类 → 3.检查是否已申请 → 回传结果
  申请: 1.登录 → 2.获取分类 → 3.执行申请 → 回传结果
"""

import traceback
import time
import base64
import datetime

import httpx
from PySide6.QtCore import QObject, Signal, QRunnable


# ========== 超级鹰配置 ==========
CJY_URL = "https://upload.chaojiying.net/Upload/Processing.php"
CJY_REPORT_URL = "https://upload.chaojiying.net/Upload/ReportError.php"
CJY_USER = "alfaa3"
CJY_PASS = "123456"
CJY_SOFT_ID = "976381"
CJY_CODE_TYPE = "4004"  # 数字字母验证码

BASE_URL = "https://www.xjyxjyw.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/148.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


class WorkerSignals(QObject):
    """Worker 信号定义，用于跨线程通信"""
    result = Signal(str, str, str, str, str)
    # result(账号, 密码, 分类, 状态, 详细信息)
    # 状态值: "登录失败" / "已申请" / "未申请" / "申请成功" / "申请失败" / "异常"

    progress = Signal(int, int)
    finished = Signal()


# ========== 超级鹰辅助函数 ==========

def _recognize_captcha(image_bytes: bytes):
    """超级鹰识别验证码，返回 (code, pic_id) 或 None"""
    try:
        img_b64 = base64.b64encode(image_bytes).decode()
        data = {
            "user": CJY_USER,
            "pass": CJY_PASS,
            "softid": CJY_SOFT_ID,
            "codetype": CJY_CODE_TYPE,
            "file_base64": img_b64,
        }
        resp = httpx.post(CJY_URL, data=data, timeout=30)
        result = resp.json()
        if result.get("err_no") == 0:
            code = result.get("pic_str", "").strip()
            pic_id = result.get("pic_id", "")
            return code, pic_id
        return None
    except Exception:
        return None


def _report_captcha_error(pic_id: str):
    """上报超级鹰验证码识别错误"""
    try:
        data = {
            "user": CJY_USER,
            "pass": CJY_PASS,
            "softid": CJY_SOFT_ID,
            "id": pic_id,
        }
        httpx.post(CJY_REPORT_URL, data=data, timeout=10)
    except Exception:
        pass


# ========== 生成 captcha URL 时间参数 ==========

def _make_captcha_date() -> str:
    """生成 JS new Date().toString() 格式的时间字符串"""
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    # 格式: Tue May 26 2026 15:53:14 GMT+0800
    weekday = now.strftime("%a")
    month = now.strftime("%b")
    day = now.day
    year = now.year
    hms = now.strftime("%H:%M:%S")
    return f"{weekday} {month} {day:02d} {year} {hms} GMT+0800"


class AccountWorker(QRunnable):
    """单个账号的执行任务"""

    def __init__(self, account: str, password: str, category: str, mode: str, signals: WorkerSignals):
        super().__init__()
        self.account = account
        self.password = password
        self.category = category
        self.mode = mode           # 'query' or 'apply'
        self.signals = signals
        self._session = httpx.Client(follow_redirects=False)

    def run(self):
        """QRunnable 的入口，子线程中执行"""
        try:
            # ----- 1. 登录 -----
            login_ok, login_msg = self.login()
            if not login_ok:
                self.signals.result.emit(
                    self.account, self.password, self.category,
                    "登录失败", login_msg
                )
                return

            # ----- 2. 根据分类获取信息 -----
            category_ok, category_msg, category_info = self.fetch_category_info()
            if not category_ok:
                self.signals.result.emit(
                    self.account, self.password, self.category,
                    "获取分类失败", category_msg
                )
                return

            # ----- 3. 查询或申请 -----
            if self.mode == "query":
                status, detail = self.check_applied(category_info)
            else:
                status, detail = self.do_apply(category_info)

            self.signals.result.emit(
                self.account, self.password, self.category,
                status, detail
            )

        except Exception as e:
            tb = traceback.format_exc()
            self.signals.result.emit(
                self.account, self.password, self.category,
                "异常", f"{e}\n{tb}"
            )
        finally:
            self._session.close()

    # ============================================================
    # 登录流程
    # ============================================================

    def login(self):
        """
        登录流程:
          1. GET mlogin.jsp → 获取 JSESSIONID
          2. GET image.jsp → 获取验证码图片
          3. POST 超级鹰 → 识别验证码
          4. POST member_login.do → 登录
        返回: (success: bool, msg: str)
        """
        try:
            # ----- 1. 访问登录页，获取 JSESSIONID -----
            resp = self._session.get(
                f"{BASE_URL}/mlogin.jsp",
                headers={**HEADERS, "Referer": f"{BASE_URL}/"},
                timeout=15,
            )
            if resp.status_code != 200:
                return False, f"访问登录页失败: HTTP {resp.status_code}"

            # ----- 2. 获取验证码图片 -----
            captcha_date = _make_captcha_date()
            captcha_url = f"{BASE_URL}/image.jsp?date={captcha_date}"
            resp_img = self._session.get(
                captcha_url,
                headers={
                    **HEADERS,
                    "Referer": f"{BASE_URL}/mlogin.jsp",
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                },
                timeout=15,
            )
            if resp_img.status_code != 200:
                return False, f"获取验证码失败: HTTP {resp_img.status_code}"

            image_bytes = resp_img.content

            # ----- 3. 超级鹰识别验证码 -----
            captcha_result = _recognize_captcha(image_bytes)
            if captcha_result is None:
                return False, "验证码识别失败（超级鹰返回异常）"

            captcha_code, pic_id = captcha_result

            # ----- 4. 发送登录请求 -----
            login_data = {
                "member.loginname": self.account,
                "member.pwd": self.password,
                "ValidateCode": captcha_code,
            }

            resp_login = self._session.post(
                f"{BASE_URL}/member_login.do",
                data=login_data,
                headers={
                    **HEADERS,
                    "Referer": f"{BASE_URL}/mlogin.jsp",
                    "Origin": BASE_URL,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=15,
            )

            # 302 = 登录成功（重定向）
            if resp_login.status_code in (302, 303, 307):
                return True, f"登录成功（验证码: {captcha_code}）"

            # 200 = 登录失败，页面包含错误信息
            if resp_login.status_code == 200:
                text = resp_login.text
                # 提取错误信息
                error_msg = "登录失败"
                if "密码错误" in text:
                    error_msg = "密码错误"
                elif "没有您的信息" in text:
                    error_msg = "账号不存在"
                elif "验证码" in text:
                    error_msg = "验证码错误"
                    if pic_id:
                        _report_captcha_error(pic_id)
                elif "用户不存在" in text:
                    error_msg = "用户不存在"
                elif "系统错误" in text:
                    error_msg = "系统错误"

                return False, f"{error_msg}（验证码: {captcha_code}）"

            return False, f"登录响应异常: HTTP {resp_login.status_code}"

        except httpx.TimeoutException:
            return False, "请求超时"
        except httpx.ConnectError:
            return False, "无法连接服务器"
        except Exception as e:
            return False, f"登录异常: {str(e)}"

    # ============================================================
    # 分类 → ID 映射
    # ============================================================

    CATEGORY_MAP = {
        "临床、医技相关专项": "202610000035",
        "临床医技相关专项":    "202610000035",
        "药学专项":            "202610000036",
        "护理专项":            "202610000034",
        "乡镇卫生院专项":      "202610000037",
    }

    def _get_category_id(self) -> str:
        """根据分类名称获取 ID，找不到则原样返回"""
        return self.CATEGORY_MAP.get(self.category, self.category)

    # ============================================================
    # 获取分类页面信息
    # ============================================================

    def fetch_category_info(self):
        """
        访问分类对应页面，获取课程列表和状态
        返回: (success: bool, msg: str, category_info: dict)
            category_info = {
                "courses": [
                    {"name": "课程名", "credits": "3.0", "status": "已申请"|"可申请"|"其他"},
                    ...
                ]
            }
        """
        try:
            cid = self._get_category_id()
            resp = self._session.get(
                f"{BASE_URL}/member/cw_info.do?id={cid}&card=",
                headers={**HEADERS, "Referer": f"{BASE_URL}/mlogin.jsp"},
                timeout=15,
            )
            if resp.status_code != 200:
                return False, f"访问分类页面失败: HTTP {resp.status_code}", {}

            html = resp.text
            import re

            # 解码 HTML 实体
            import html as html_mod
            html = html_mod.unescape(html)

            # 提取表格中的课程行
            courses = []
            # 用正则提取每条 tr
            rows = re.findall(r'<tr>.*?</tr>', html, re.DOTALL)
            for row in rows:
                tds = re.findall(r'<td>(.*?)</td>', row, re.DOTALL)
                if len(tds) < 3:
                    continue

                # td1: 课程名称
                name = re.sub(r'<[^>]+>', '', tds[0]).strip()

                # td2: 学分
                credits = re.sub(r'<[^>]+>', '', tds[1]).strip()

                # 从该行提取 course_id（从链接参数 id= 中取）
                course_id = ""
                id_match = re.search(r'[?&]id=(\d+)', row)
                if id_match:
                    course_id = id_match.group(1)
                else:
                    # 试试 course_id= 参数
                    id_match = re.search(r'course_id=(\d+)', row)
                    if id_match:
                        course_id = id_match.group(1)

                # td3: 状态
                status_html = tds[2]
                if "已申请学分" in status_html:
                    course_status = "已申请"
                elif "申请学分" in status_html:
                    course_status = "可申请"
                else:
                    raw_status = re.sub(r'<[^>]+>', '', status_html).strip()
                    course_status = raw_status if raw_status else "其他"

                courses.append({
                    "name": name,
                    "credits": credits,
                    "course_id": course_id,
                    "status": course_status,
                })

            if not courses:
                return False, "页面未解析到课程数据", {}

            return True, f"找到 {len(courses)} 门课程", {"courses": courses}

        except httpx.TimeoutException:
            return False, "请求超时", {}
        except Exception as e:
            return False, f"获取分类信息异常: {str(e)}", {}

    # ============================================================
    # 检查是否已申请
    # ============================================================

    def check_applied(self, category_info: dict):
        """
        检查该分类下所有课程是否都已申请
        返回: (status: str, detail: str)
            "已申请" — 所有课程都已申请
            "未申请" — 还有可申请的课程
            "未学习" — 课程未学习，还不能申请
        """
        courses = category_info.get("courses", [])

        applied_count = sum(1 for c in courses if c["status"] == "已申请")
        available_count = sum(1 for c in courses if c["status"] == "可申请")
        unlearn_count = sum(1 for c in courses if c["status"] not in ("已申请", "可申请"))
        total = len(courses)

        if applied_count == total:
            return "已申请", f"所有课程已申请（{total}门）"
        elif available_count > 0:
            return "未申请", f"还有 {available_count}/{total} 门课程可申请"
        elif unlearn_count > 0:
            return "未学习", f"课程未完成学习（{unlearn_count}/{total}门）"
        else:
            return "未申请", f"课程列表共 {total} 门"

    # ============================================================
    # 执行申请
    # ============================================================

    def do_apply(self, category_info: dict):
        """
        遍历分类下所有可申请的课程，使用学习卡提交申请
        返回: (status: str, detail: str)
        """
        import re

        courses = category_info.get("courses", [])
        all_applied = all(c["status"] == "已申请" for c in courses)
        if all_applied:
            return "已申请", "所有课程已申请，无需重复申请"

        can_apply = [c for c in courses if c["status"] == "可申请" and c.get("course_id")]

        if not can_apply:
            # 有课程但不是可申请状态（未学习等）
            statuses = {c["status"] for c in courses}
            return "申请失败", f"没有可申请的课程（当前状态: {', '.join(statuses)}）"

        applied_ok = []
        applied_fail = []

        for course in can_apply:
            course_id = course["course_id"]
            course_name = course["name"]

            # ----- 1. 访问申请页面，获取学习卡 -----
            try:
                resp = self._session.get(
                    f"{BASE_URL}/member/apply_apply.do?course_id={course_id}",
                    headers={**HEADERS, "Referer": f"{BASE_URL}/member/cw_info.do?id={self._get_category_id()}"},
                    timeout=15,
                )
                if resp.status_code != 200:
                    applied_fail.append(f"{course_name}: 访问申请页失败 HTTP {resp.status_code}")
                    continue

                html = resp.text
            except Exception as e:
                applied_fail.append(f"{course_name}: 访问申请页异常 {str(e)}")
                continue

            # ----- 2. 解析学习卡列表 -----
            # 找表格行: 卡号 密码
            card_rows = re.findall(
                r"<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*<td>(\d+)</td>\s*<td>(\d+)</td>",
                html, re.DOTALL
            )

            if not card_rows:
                applied_fail.append(f"{course_name}: 未购买学习卡")
                continue

            # 用第一张卡
            card_type = card_rows[0][0].strip()
            card_category = card_rows[0][1].strip()
            card_no = card_rows[0][2]
            card_passwd = card_rows[0][3]

            # ----- 3. 提交申请 -----
            try:
                apply_url = (
                    f"{BASE_URL}/member/apply_applyCard.do"
                    f"?courseLog.cid={course_id}"
                    f"&cardNo={card_no}"
                    f"&cardPasswd={card_passwd}"
                )
                resp2 = self._session.get(
                    apply_url,
                    headers={
                        **HEADERS,
                        "Referer": f"{BASE_URL}/member/apply_apply.do?course_id={course_id}",
                    },
                    timeout=15,
                )

                if "申请成功" in resp2.text:
                    applied_ok.append(f"{course_name}")
                else:
                    # 找错误信息
                    err_text = resp2.text
                    err_msg = "申请失败"
                    for kw in ["申请成功", "已申请", "失败", "错误", "不存在", "过期"]:
                        if kw in err_text and kw != "申请成功":
                            idx = err_text.find(kw)
                            err_msg = err_text[max(0, idx - 20):idx + 50]
                            break
                    applied_fail.append(f"{course_name}: {err_msg}")
            except Exception as e:
                applied_fail.append(f"{course_name}: 提交申请异常 {str(e)}")

        # ----- 汇总结果 -----
        if applied_ok and not applied_fail:
            return "申请成功", f"全部申请成功: {' / '.join(applied_ok)}"
        elif applied_ok and applied_fail:
            fail_msgs = "; ".join(applied_fail)
            return "申请失败", f"部分成功: {' / '.join(applied_ok)} | 失败: {fail_msgs}"
        else:
            fail_msgs = "; ".join(applied_fail)
            return "申请失败", fail_msgs

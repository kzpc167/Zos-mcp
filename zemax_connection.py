"""Zemax OpticStudio COM 连接管理 (兼容 2018 版).

参考 PyZOS (https://github.com/xzos/pyzos) 的 CastTo / _prop_map_get_ 策略，
实现多层安全属性访问、gen_py 缓存清理和自动重连。
"""

import os
import shutil
import time

from logger import logger


class ZemaxConnection:
    """通过 COM 接口 (ZOS-API) 管理与 OpticStudio 的连接."""

    def __init__(self):
        self._connection = None
        self._app = None
        self._system = None
        self._constants = None
        # 保存连接参数以用于后续 reconnect
        self._mode = "extension"
        self._instance = 0

    # ------------------------------------------------------------------
    #  gen_py 缓存清理 (参考 PyZOS: 避免旧包装器导致属性丢失)
    # ------------------------------------------------------------------
    @staticmethod
    def clear_gen_py_cache():
        """删除 win32com gen_py 缓存中的 ZOSAPI 条目, 强制重新生成包装器."""
        import win32com
        gen_py_dir = os.path.join(os.path.dirname(win32com.__gen_path__), "")
        if not os.path.isdir(win32com.__gen_path__):
            return
        # ZOSAPI 的两个类型库 GUID
        zos_guids = [
            "EA433010-2BAC-43C4-857C-7AEAC4A8CCE0",
            "F66684D7-AAFE-4A62-9156-FF7A7853F764",
        ]
        for item in os.listdir(win32com.__gen_path__):
            for guid in zos_guids:
                if guid.lower().replace("-", "") in item.lower().replace("-", ""):
                    target = os.path.join(win32com.__gen_path__, item)
                    if os.path.isdir(target):
                        shutil.rmtree(target, ignore_errors=True)
                    elif os.path.isfile(target):
                        os.remove(target)

    # ------------------------------------------------------------------
    #  连接
    # ------------------------------------------------------------------
    def connect(self, mode="extension", instance=0):
        """连接到 OpticStudio.

        Args:
            mode: "extension" 连接到运行中的实例, "standalone" 启动新实例
            instance: Extension 实例编号 (默认 0)
        """
        from win32com.client import CastTo, constants, gencache
        from win32com.client.gencache import EnsureDispatch

        self._mode = mode
        self._instance = instance

        # 注册 ZOS-API COM 类型库
        gencache.EnsureModule("{EA433010-2BAC-43C4-857C-7AEAC4A8CCE0}", 0, 1, 0)
        gencache.EnsureModule("{F66684D7-AAFE-4A62-9156-FF7A7853F764}", 0, 1, 0)

        self._connection = EnsureDispatch("ZOSAPI.ZOSAPI_Connection")
        if self._connection is None:
            raise ConnectionError("无法初始化 ZOSAPI COM 连接")

        if mode == "extension":
            self._app = self._connection.ConnectAsExtension(instance)
        elif mode == "standalone":
            self._app = self._connection.CreateNewApplication()
        else:
            raise ValueError(f"未知连接模式: {mode}")

        if self._app is None:
            raise ConnectionError(
                "无法连接到 OpticStudio。请确保:\n"
                "  1. OpticStudio 正在运行\n"
                "  2. 已点击 Programming > Interactive Extension"
            )

        if not self._app.IsValidLicenseForAPI:
            raise ConnectionError("当前许可证不支持 ZOS-API 使用")

        self._system = self._app.PrimarySystem
        if self._system is None:
            raise ConnectionError("无法获取主光学系统")

        self._constants = constants

        # 启动时诊断 COM 属性映射并缓存 (见 probe_interface)
        self._prop_cache = {}
        self._probe_interfaces()

        logger.info(f"OpticStudio 连接成功: mode={mode}, instance={instance}, serial={self._app.SerialCode}")
        return True

    # ------------------------------------------------------------------
    #  接口属性诊断 (参考 PyZOS zosutils.get_properties / wrapped_zos_object)
    # ------------------------------------------------------------------
    def _probe_interfaces(self):
        """探测 IWavelength / IField 等关键接口的真实属性名并缓存.

        PyZOS 使用 _prop_map_get_ 字典来发现属性；本方法做同等的探测，
        在连接建立时一次性完成，此后工具层直接使用缓存结果。
        """
        from win32com.client import CastTo

        # --- IWavelength ---
        wl_props = self._detect_wavelength_props()
        self._prop_cache["IWavelength"] = wl_props

        # --- IField ---
        fl_props = self._detect_field_props()
        self._prop_cache["IField"] = fl_props

    def _detect_wavelength_props(self):
        """探测 IWavelength 对象上 value/weight 的实际可用属性名."""
        mapping = {"value": None, "weight": None}
        try:
            wls = self._system.SystemData.Wavelengths
            if wls.NumberOfWavelengths < 1:
                return mapping
            w = wls.GetWavelength(1)
            # 策略 1: 直接属性 (早期绑定生成的名称)
            mapping["value"] = _find_prop(w, ["Value", "Wavelength", "WavelengthValue", "value"])
            mapping["weight"] = _find_prop(w, ["Weight", "weight"])
            # 策略 2: 从 _prop_map_get_ 字典探测 (参考 PyZOS zosutils.get_properties)
            if mapping["value"] is None:
                mapping["value"] = _find_in_propmap(w, ["value", "wavelength"])
            if mapping["weight"] is None:
                mapping["weight"] = _find_in_propmap(w, ["weight"])
        except Exception:
            pass
        return mapping

    def _detect_field_props(self):
        """探测 IField 对象上 x/y/weight 的实际可用属性名."""
        mapping = {"x": None, "y": None, "weight": None}
        try:
            flds = self._system.SystemData.Fields
            if flds.NumberOfFields < 1:
                return mapping
            f = flds.GetField(1)
            mapping["x"] = _find_prop(f, ["X", "x", "FieldX"])
            mapping["y"] = _find_prop(f, ["Y", "y", "FieldY"])
            mapping["weight"] = _find_prop(f, ["Weight", "weight"])
        except Exception:
            pass
        return mapping

    def get_wavelength_data(self, wl_obj):
        """安全获取 IWavelength 的 value 和 weight."""
        m = self._prop_cache.get("IWavelength", {})
        value = _safe_get(wl_obj, m.get("value")) if m.get("value") else _safe_get_multi(wl_obj, ["Value", "Wavelength"])
        weight = _safe_get(wl_obj, m.get("weight")) if m.get("weight") else _safe_get_multi(wl_obj, ["Weight"])
        return value, weight

    def set_wavelength_data(self, wl_obj, value=None, weight=None):
        """安全设置 IWavelength 的 value 和 weight."""
        m = self._prop_cache.get("IWavelength", {})
        if value is not None:
            prop = m.get("value") or _find_prop(wl_obj, ["Value", "Wavelength"]) or "Value"
            _safe_set(wl_obj, prop, value)
        if weight is not None:
            prop = m.get("weight") or _find_prop(wl_obj, ["Weight"]) or "Weight"
            _safe_set(wl_obj, prop, weight)

    def get_field_data(self, field_obj):
        """安全获取 IField 的 x, y, weight."""
        m = self._prop_cache.get("IField", {})
        x = _safe_get(field_obj, m.get("x")) if m.get("x") else _safe_get_multi(field_obj, ["X", "FieldX"])
        y = _safe_get(field_obj, m.get("y")) if m.get("y") else _safe_get_multi(field_obj, ["Y", "FieldY"])
        weight = _safe_get(field_obj, m.get("weight")) if m.get("weight") else _safe_get_multi(field_obj, ["Weight"])
        return x, y, weight

    def set_field_data(self, field_obj, x=None, y=None, weight=None):
        """安全设置 IField 的 x, y, weight."""
        m = self._prop_cache.get("IField", {})
        if x is not None:
            prop = m.get("x") or _find_prop(field_obj, ["X", "FieldX"]) or "X"
            _safe_set(field_obj, prop, x)
        if y is not None:
            prop = m.get("y") or _find_prop(field_obj, ["Y", "FieldY"]) or "Y"
            _safe_set(field_obj, prop, y)
        if weight is not None:
            prop = m.get("weight") or _find_prop(field_obj, ["Weight"]) or "Weight"
            _safe_set(field_obj, prop, weight)

    # ------------------------------------------------------------------
    #  连接状态检测与重连 (参考 PyZOS _PyZOSApp.connect.IsAlive)
    # ------------------------------------------------------------------
    @property
    def is_alive(self) -> bool:
        """检测 COM 连接是否仍然存活."""
        try:
            if self._connection is None:
                return False
            return bool(self._connection.IsAlive)
        except Exception:
            return False

    def reconnect(self, max_retries=3, retry_delay=2.0):
        """断开并重新连接到 OpticStudio.

        Args:
            max_retries: 最大重试次数
            retry_delay: 重试间隔 (秒)
        Returns:
            True 成功, False 失败
        """
        self.disconnect()
        for attempt in range(1, max_retries + 1):
            try:
                self.connect(mode=self._mode, instance=self._instance)
                logger.info(f"重连成功（第 {attempt} 次）")
                return True
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"重连尝试 {attempt}/{max_retries} 失败: {e}")
                    print(f"\033[33m  重连尝试 {attempt}/{max_retries} 失败: {e}\033[0m")
                    print(f"\033[33m  请确保 OpticStudio 已打开 Interactive Extension，{retry_delay}秒后重试...\033[0m")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"重连彻底失败（{max_retries}次）: {e}")
                    print(f"\033[31m  重连失败 ({max_retries}次尝试): {e}\033[0m")
        return False

    # ------------------------------------------------------------------
    #  属性访问
    # ------------------------------------------------------------------
    @property
    def app(self):
        return self._app

    @property
    def system(self):
        return self._system

    @property
    def constants(self):
        return self._constants

    @property
    def lde(self):
        """Lens Data Editor."""
        return self._system.LDE

    @property
    def mfe(self):
        """Merit Function Editor."""
        return self._system.MFE

    @property
    def system_data(self):
        return self._system.SystemData

    def disconnect(self):
        logger.info("断开 OpticStudio 连接")
        self._connection = None
        self._app = None
        self._system = None


# ---------------------------------------------------------------------------
#  模块级辅助函数 (参考 PyZOS zosutils.get_properties / _prop_map_get_)
# ---------------------------------------------------------------------------

def _find_prop(obj, candidates):
    """在 COM 对象上尝试多个属性名, 返回第一个能成功读取的属性名."""
    for name in candidates:
        try:
            _ = getattr(obj, name)
            return name
        except Exception:
            continue
    return None


def _find_in_propmap(obj, keywords):
    """从 COM 对象的 _prop_map_get_ 中模糊匹配属性名."""
    prop_map = getattr(obj, "_prop_map_get_", None)
    if not prop_map:
        return None
    for key in prop_map:
        for kw in keywords:
            if kw.lower() in key.lower():
                # 验证能读取
                try:
                    _ = getattr(obj, key)
                    return key
                except Exception:
                    continue
    return None


def _safe_get(obj, attr, default=None):
    """安全获取 COM 对象属性值."""
    if attr is None:
        return default
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def _safe_get_multi(obj, candidates, default=None):
    """尝试多个属性名, 返回第一个成功的值."""
    for name in candidates:
        try:
            return getattr(obj, name)
        except Exception:
            continue
    # 最后尝试 _prop_map_get_
    prop_map = getattr(obj, "_prop_map_get_", None)
    if prop_map:
        for key in prop_map:
            try:
                return getattr(obj, key)
            except Exception:
                continue
    return default


def _safe_set(obj, attr, value):
    """安全设置 COM 对象属性."""
    try:
        setattr(obj, attr, value)
        return True
    except Exception:
        # 尝试通过 _prop_map_put_ 查找可设置的属性
        prop_map = getattr(obj, "_prop_map_put_", None)
        if prop_map:
            for key in prop_map:
                if key.lower() == attr.lower():
                    try:
                        setattr(obj, key, value)
                        return True
                    except Exception:
                        pass
        raise
        self._system = None

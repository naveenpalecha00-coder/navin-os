-- NAVIN OS Build 10: better Bluetooth audio + TWS auto-reconnect.
-- Codecs are used only when the installed PipeWire build supports them.
bluez_monitor.properties["bluez5.enable-sbc-xq"] = true
bluez_monitor.properties["bluez5.enable-msbc"] = true
bluez_monitor.properties["bluez5.enable-hw-volume"] = true
bluez_monitor.properties["bluez5.codecs"] = "[ ldac aptx_hd aptx aac sbc_xq sbc ]"
bluez_monitor.properties["bluez5.auto-connect"] = "[ hfp_hf hsp_hs a2dp_sink ]"

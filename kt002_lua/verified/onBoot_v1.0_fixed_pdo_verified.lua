-- ============================================================
-- KT002 DOE6 Direct-USB Fixed PDO Controller
-- File name: onBoot.lua
--
-- Communication:
--   Raspberry Pi Python
--     -> USB Shizuku Lua_MOSI
--     -> tcp.onReceived()
--     -> this Lua script
--
-- Supported commands:
--   PING
--   HELLO
--   PD_5V
--   PD_9V
--   PD_12V
--   PD_15V
--   PD_20V
--
-- Startup behavior:
--   Only waits for Raspberry Pi commands.
--   Does not initialize PD at startup.
--   Does not change voltage automatically.
--
-- Verified base:
--   5V -> 9V -> 5V
-- ============================================================


local SOURCE_CAP_TIMEOUT_MS = 3000
local REQUEST_SETTLE_MS = 1000
local VOLTAGE_TOLERANCE = 0.25

local screen_ready = false
local command_busy = false
local pd_initialized = false

local source_caps = {}
local source_cap_count = 0


-- ============================================================
-- Display message
-- ============================================================

local function show_message(
    title,
    message,
    display_color
)
    if not screen_ready then
        return
    end

    screen.clear()

    screen.showDialog(
        title,
        message,
        0,
        false,
        display_color
    )
end


-- ============================================================
-- Send Lua reply
-- ============================================================

local function send_reply(message)
    print(message)
    tcp.write(message .. "\n")
end


-- ============================================================
-- Normalize incoming command
-- ============================================================

local function normalize_command(command)
    if command == nil then
        return ""
    end

    command = string.gsub(
        command,
        "\r",
        ""
    )

    command = string.gsub(
        command,
        "\n",
        ""
    )

    command = string.gsub(
        command,
        "^%s+",
        ""
    )

    command = string.gsub(
        command,
        "%s+$",
        ""
    )

    return string.upper(command)
end


-- ============================================================
-- Wait for PD Source Capabilities
-- ============================================================

local function wait_for_source_capability()
    local remaining =
        SOURCE_CAP_TIMEOUT_MS

    while remaining > 0 do
        if pdSink.isSrcCapReceived() then
            return true
        end

        delay.ms(1)

        remaining =
            remaining - 1
    end

    return false
end


-- ============================================================
-- Read and cache Source Capabilities
-- ============================================================

local function read_source_capabilities()
    source_caps = {}

    source_cap_count =
        pdSink.getNumofSrcCap()

    if source_cap_count <= 0 then
        return false
    end

    print(
        string.format(
            "Source Capability count: %d",
            source_cap_count
        )
    )

    for index = 0,
        source_cap_count - 1 do

        local cap =
            pdSink.getSrcCap(index)

        source_caps[index] = cap

        if cap.type ==
            pdSink.FIXED then

            print(
                string.format(
                    "PDO[%d] FIXED %.2fV %.2fA",
                    index,
                    cap.voltage,
                    cap.currentMax
                )
            )

        elseif cap.type ==
            pdSink.AUGMENTED then

            print(
                string.format(
                    "PDO[%d] PPS %.2fV-%.2fV %.2fA",
                    index,
                    cap.voltage,
                    cap.voltageMax,
                    cap.currentMax
                )
            )

        else
            print(
                string.format(
                    "PDO[%d] UNKNOWN",
                    index
                )
            )
        end
    end

    return true
end


-- ============================================================
-- Initialize PD
--
-- Verified initialization sequence:
--
--   fastChgTrig.open()
--   pdSink.init()
--   wait for Source Capabilities
--
-- If the first wait times out:
--
--   pdSink.sendHardReset()
--   pdSink.init()
--   wait again
-- ============================================================

local function initialize_pd()
    if pd_initialized then
        return true
    end

    print("PD initialization starting")

    local open_result =
        fastChgTrig.open()

    if open_result ~=
        fastChgTrig.OK then

        send_reply(
            "ERROR:FASTCHG_OPEN_FAILED"
        )

        show_message(
            "KT002 ERROR",
            "Fast charge open failed",
            color.red
        )

        return false
    end

    print("Fast charge opened")

    pdSink.init()

    print("PD Sink initialized")

    if pdSink.getCCStatus()
        == pdSink.NO_SRC_ATTACHED then

        send_reply(
            "ERROR:NO_PD_SOURCE"
        )

        show_message(
            "KT002 ERROR",
            "No PD source attached",
            color.red
        )

        return false
    end

    print(
        "Waiting for Source Capabilities"
    )

    local received =
        wait_for_source_capability()

    if not received then
        print(
            "Source Capability timeout"
        )

        print(
            "Sending PD hard reset"
        )

        pdSink.sendHardReset()
        pdSink.init()

        print(
            "Waiting for Source Capabilities again"
        )

        received =
            wait_for_source_capability()

        if not received then
            send_reply(
                "ERROR:SOURCE_CAP_TIMEOUT"
            )

            show_message(
                "KT002 ERROR",
                "Source capability timeout",
                color.red
            )

            return false
        end
    end

    print(
        "Source Capabilities received"
    )

    if not read_source_capabilities() then
        send_reply(
            "ERROR:NO_SOURCE_CAPABILITY"
        )

        show_message(
            "KT002 ERROR",
            "No PDO found",
            color.red
        )

        return false
    end

    pd_initialized = true

    send_reply(
        string.format(
            "OK:PD_INITIALIZED:%d",
            source_cap_count
        )
    )

    return true
end


-- ============================================================
-- Request Fixed PDO
-- ============================================================

local function request_fixed_voltage(
    target_voltage
)
    if not initialize_pd() then
        return false
    end

    print(
        string.format(
            "Searching for %dV PDO",
            target_voltage
        )
    )

    for index = 0,
        source_cap_count - 1 do

        local cap =
            source_caps[index]

        if cap.type ==
            pdSink.FIXED then

            if math.abs(
                cap.voltage -
                target_voltage
            ) < VOLTAGE_TOLERANCE then

                print(
                    string.format(
                        "Requesting PDO[%d] %.2fV %.2fA",
                        index,
                        cap.voltage,
                        cap.currentMax
                    )
                )

                local result =
                    pdSink.request(
                        index,
                        cap.voltage,
                        cap.currentMax
                    )

                if result ~=
                    pdSink.OK then

                    send_reply(
                        string.format(
                            "ERROR:REQUEST_FAILED:"
                                .. "PD_%dV:PDO=%d",
                            target_voltage,
                            index
                        )
                    )

                    show_message(
                        "KT002 ERROR",
                        "PD request failed",
                        color.red
                    )

                    return false
                end

                delay.ms(
                    REQUEST_SETTLE_MS
                )

                meter.setDataSource(
                    meter.INSTANT
                )

                local measured_voltage =
                    meter.readVoltage()

                print(
                    string.format(
                        "Measured voltage: %.3fV",
                        measured_voltage
                    )
                )

                send_reply(
                    string.format(
                        "OK:PD_%dV:%.3fV:PDO=%d",
                        target_voltage,
                        measured_voltage,
                        index
                    )
                )

                show_message(
                    "KT002 PDO OK",
                    string.format(
                        "%dV requested\nMeasured %.3fV",
                        target_voltage,
                        measured_voltage
                    ),
                    color.green
                )

                return true
            end
        end
    end

    send_reply(
        string.format(
            "ERROR:PDO_%dV_NOT_FOUND",
            target_voltage
        )
    )

    show_message(
        "KT002 ERROR",
        string.format(
            "%dV PDO not found",
            target_voltage
        ),
        color.red
    )

    return false
end


-- ============================================================
-- Process one Raspberry Pi command
-- ============================================================

local function process_command(command)
    if command == "PING"
        or command == "HELLO" then

        send_reply(
            "PONG:KT002"
        )

        show_message(
            "KT002 ONLINE",
            "Raspberry Pi connected",
            color.green
        )

    elseif command == "PD_5V"
        or command == "5" then

        request_fixed_voltage(5)

    elseif command == "PD_9V"
        or command == "9" then

        request_fixed_voltage(9)

    elseif command == "PD_12V"
        or command == "12" then

        request_fixed_voltage(12)

    elseif command == "PD_15V"
        or command == "15" then

        request_fixed_voltage(15)

    elseif command == "PD_20V"
        or command == "20" then

        request_fixed_voltage(20)

    else
        send_reply(
            "ERROR:UNKNOWN_COMMAND:"
                .. command
        )

        show_message(
            "KT002 ERROR",
            "Unknown command",
            color.red
        )
    end
end


-- ============================================================
-- Lua_MOSI receive callback
-- ============================================================

function usb_command_received()
    if command_busy then
        send_reply(
            "ERROR:BUSY"
        )

        return
    end

    local raw_command =
        tcp.readAll()

    local command =
        normalize_command(
            raw_command
        )

    if command == "" then
        return
    end

    command_busy = true

    print(
        "RX: " .. command
    )

    local success,
          error_message =
        pcall(
            process_command,
            command
        )

    if not success then
        local error_text =
            tostring(error_message)

        print(
            "LUA ERROR: "
                .. error_text
        )

        send_reply(
            "ERROR:LUA:"
                .. error_text
        )

        show_message(
            "KT002 LUA ERROR",
            error_text,
            color.red
        )
    end

    command_busy = false
end


-- ============================================================
-- Startup
-- ============================================================

print(
    "KT002 Fixed PDO controller starting"
)

local screen_result =
    screen.open()

if screen_result ~=
    screen.OK then

    print(
        "ERROR:SCREEN_OPEN_FAILED"
    )

    os.exit(1)
end

screen_ready = true

show_message(
    "KT002 DOE6",
    "Waiting for Raspberry Pi...",
    color.yellow
)

tcp.open()

tcp.onReceived(
    usb_command_received
)

send_reply(
    "READY:KT002_FIXED_PDO"
)

print(
    "KT002 Fixed PDO event loop ready"
)
-- AI Session Usage, the Rainmeter skin's script: the helper's JSON answers become rows, bars and texts.
-- Rainmeter embeds Lua 5.1. Everything that touches Rainmeter goes through RM (SKIN:...), so the logic runs under
-- a plain lua5.1 in the tests (tests/test_skin_lua.py) with a stub SKIN. No em dash anywhere: the whole tree ships.

local MAX_ROWS = 8
local PROVIDERS = {
    { id = "claude", measure = "mClaude", name = "Claude", cli = "Claude Code", show = "ShowClaude" },
    { id = "codex", measure = "mCodex", name = "ChatGPT", cli = "Codex", show = "ShowCodex" },
}
-- The messages of the Plasma widget, for the same error kinds.
local MESSAGES = {
    nologin = "No %s subscription login found",
    nocli = "%s not found: install it, or set its program in the skin's variables",
    cli = "%s could not tell the usage: %s",
    nostatusline = "No numbers from %s's status line yet",
    unreadable = "Cannot use the status file: %s",
    format = "Unexpected answer; %s may have changed what it reports",
    timeout = "No answer from the helper; will retry",
    badoutput = "The helper gave no usable answer: %s",
    usage = "The helper refused its arguments: %s",
}

local state = {}      -- provider id -> the last answer: { ok, rows, error, message, at }
local last_good = {}  -- provider id -> the last good answer, kept dimmed under an error

-- ---- Rainmeter, behind one table ----------------------------------------------------------------------------
local RM = {}
function RM.var(name, default)
    local v = SKIN:GetVariable(name)
    if v == nil or v == "" then return default end
    return v
end
function RM.measure_string(name)
    local m = SKIN:GetMeasure(name)
    return m and m:GetStringValue() or ""
end
function RM.bang(...) SKIN:Bang(...) end

-- ---- JSON: the helper's one line (objects, arrays, strings with escapes, numbers, true, false, null) ----------
local json = { null = setmetatable({}, { __tostring = function() return "null" end }) }
local function fail(i, msg) error(string.format("json: %s at %d", msg, i), 0) end
local function skip_ws(s, i) return s:find("[^ \t\r\n]", i) or #s + 1 end
local function utf8_char(code)
    if code < 0x80 then return string.char(code) end
    if code < 0x800 then return string.char(0xC0 + math.floor(code / 0x40), 0x80 + code % 0x40) end
    if code < 0x10000 then
        return string.char(0xE0 + math.floor(code / 0x1000), 0x80 + math.floor(code / 0x40) % 0x40, 0x80 + code % 0x40)
    end
    return string.char(0xF0 + math.floor(code / 0x40000), 0x80 + math.floor(code / 0x1000) % 0x40,
                       0x80 + math.floor(code / 0x40) % 0x40, 0x80 + code % 0x40)
end
local ESCAPES = { ['"'] = '"', ["\\"] = "\\", ["/"] = "/", b = "\b", f = "\f", n = "\n", r = "\r", t = "\t" }
local decode_value
local function decode_string(s, i)
    local out, j = {}, i + 1
    while true do
        local c = s:sub(j, j)
        if c == "" then fail(j, "unterminated string") end
        if c == '"' then return table.concat(out), j + 1 end
        if c == "\\" then
            local e = s:sub(j + 1, j + 1)
            if e == "u" then
                local code = tonumber(s:sub(j + 2, j + 5), 16)
                if not code then fail(j, "bad \\u escape") end
                j = j + 6
                if code >= 0xD800 and code <= 0xDBFF and s:sub(j, j + 1) == "\\u" then
                    local low = tonumber(s:sub(j + 2, j + 5), 16)
                    if low and low >= 0xDC00 and low <= 0xDFFF then
                        code = 0x10000 + (code - 0xD800) * 0x400 + (low - 0xDC00)
                        j = j + 6
                    end
                end
                out[#out + 1] = utf8_char(code)
            else
                local r = ESCAPES[e]
                if not r then fail(j, "bad escape") end
                out[#out + 1] = r
                j = j + 2
            end
        else
            out[#out + 1] = c
            j = j + 1
        end
    end
end
local function decode_number(s, i)
    local j = s:find("[^-+0-9.eE]", i) or #s + 1
    local n = tonumber(s:sub(i, j - 1))
    if n == nil then fail(i, "bad number") end
    return n, j
end
decode_value = function(s, i)
    i = skip_ws(s, i)
    local c = s:sub(i, i)
    if c == "{" then
        local obj = {}
        i = skip_ws(s, i + 1)
        if s:sub(i, i) == "}" then return obj, i + 1 end
        while true do
            if s:sub(i, i) ~= '"' then fail(i, "key expected") end
            local key
            key, i = decode_string(s, i)
            i = skip_ws(s, i)
            if s:sub(i, i) ~= ":" then fail(i, "colon expected") end
            local value
            value, i = decode_value(s, i + 1)
            obj[key] = value
            i = skip_ws(s, i)
            local d = s:sub(i, i)
            if d == "}" then return obj, i + 1 end
            if d ~= "," then fail(i, "comma expected") end
            i = skip_ws(s, i + 1)
        end
    elseif c == "[" then
        local arr = {}
        i = skip_ws(s, i + 1)
        if s:sub(i, i) == "]" then return arr, i + 1 end
        while true do
            local value
            value, i = decode_value(s, i)
            arr[#arr + 1] = value
            i = skip_ws(s, i)
            local d = s:sub(i, i)
            if d == "]" then return arr, i + 1 end
            if d ~= "," then fail(i, "comma expected") end
            i = i + 1
        end
    elseif c == '"' then return decode_string(s, i)
    elseif s:sub(i, i + 3) == "true" then return true, i + 4
    elseif s:sub(i, i + 4) == "false" then return false, i + 5
    elseif s:sub(i, i + 3) == "null" then return json.null, i + 4
    end
    return decode_number(s, i)
end
function json.decode(s)
    local v, i = decode_value(s, 1)
    i = skip_ws(s, i)
    if i <= #s then fail(i, "trailing characters") end
    return v
end

-- ---- time: the helper's ISO 8601 UTC reset times against the clock ------------------------------------------
local function days_from_civil(y, m, d)
    -- days from 1970-01-01 to a Gregorian date (Howard Hinnant's algorithm): plain arithmetic, no time zone
    if m <= 2 then y = y - 1 end
    local era = math.floor(y / 400)
    local yoe = y - era * 400
    local doy = math.floor((153 * ((m + 9) % 12) + 2) / 5) + d - 1
    local doe = yoe * 365 + math.floor(yoe / 4) - math.floor(yoe / 100) + doy
    return era * 146097 + doe - 719468
end
local function utc_epoch(y, mo, d, h, mi, s)
    -- not os.time, which reads a table as local time: correcting that by the gap between the local and the UTC
    -- reading counted summer time twice, and every reset read an hour late under it
    return days_from_civil(y, mo, d) * 86400 + h * 3600 + mi * 60 + s
end
local function parse_iso(iso)
    if type(iso) ~= "string" then return nil end
    local y, mo, d, h, mi, s = iso:match("^(%d%d%d%d)%-(%d%d)%-(%d%d)T(%d%d):(%d%d):(%d%d)")
    if not y then return nil end
    local t = utc_epoch(tonumber(y), tonumber(mo), tonumber(d), tonumber(h), tonumber(mi), tonumber(s))
    local sign, oh, om = iso:match("([+-])(%d%d):(%d%d)$")
    if sign then
        local off = tonumber(oh) * 3600 + tonumber(om) * 60
        t = t - (sign == "+" and off or -off)
    end
    return t
end
local function reset_text(iso, now)
    local t = parse_iso(iso)
    if not t then return "" end
    local diff = t - now
    if diff < -60 then return "Reset passed" end
    if diff <= 30 then return "Resets now" end
    local mins = math.floor(diff / 60 + 0.5)
    local h, m = math.floor(mins / 60), mins % 60
    local left
    if h >= 24 then left = string.format("%dd %dh", math.floor(h / 24), h % 24)
    elseif h > 0 then left = string.format("%dh %dm", h, m)
    else left = string.format("%dm", m) end
    local when
    if diff < 6 * 86400 then
        when = os.date(diff >= 86400 and "%a %H:%M" or "%H:%M", t)
    else
        when = os.date("%d %b", t)
    end
    return "Resets in " .. left .. " " .. string.char(0xC2, 0xB7) .. " " .. when
end

-- ---- the answers -------------------------------------------------------------------------------------------
local function parse_answer(text)
    local ok, parsed = pcall(json.decode, text or "")
    if not ok or type(parsed) ~= "table" then
        return { ok = false, error = "badoutput", message = (text or ""):sub(-160) }
    end
    if parsed.ok == true and type(parsed.rows) == "table" and #parsed.rows > 0 then
        local rows = {}
        for _, r in ipairs(parsed.rows) do
            if type(r) == "table" and type(r.percent) == "number" then
                rows[#rows + 1] = { label = tostring(r.label or r.id or "Limit"), percent = r.percent,
                                    resets_at = type(r.resets_at) == "string" and r.resets_at or nil }
            end
        end
        if #rows > 0 then return { ok = true, rows = rows } end
        return { ok = false, error = "badoutput", message = "no rows" }
    end
    return { ok = false, error = type(parsed.error) == "string" and parsed.error or "unknown",
             message = type(parsed.message) == "string" and parsed.message or "" }
end

local function helper_parameter(provider)
    local script = RM.var("@", "") .. "code\\fetch_usage.py"
    local parts = { RM.var("PythonArgs", "-B"), '"' .. script .. '"', "--provider", provider.id }
    if provider.id == "claude" then
        parts[#parts + 1] = "--source"
        parts[#parts + 1] = RM.var("ClaudeSource", "claudecode")
        local program = RM.var("ClaudeProgram", "")
        if program ~= "" then parts[#parts + 1] = '--claude "' .. program .. '"' end
    else
        local program = RM.var("CodexProgram", "")
        if program ~= "" then parts[#parts + 1] = '--codex "' .. program .. '"' end
    end
    return table.concat(parts, " ")
end

-- ---- the layout: which meters show, where, with what ---------------------------------------------------------
local function level_color(percent, warn, critical)
    if critical > 0 and percent >= critical then return RM.var("CriticalColor", "218,68,83") end
    if warn > 0 and percent >= warn then return RM.var("WarnColor", "246,116,0") end
    return RM.var("AccentColor", "61,174,233")
end

-- Returns the list of placements the renderer applies; pure, so the tests can read it.
function Layout(now)
    local out = {}
    local y = tonumber(RM.var("PadTop", "12")) + 26
    local row_h = tonumber(RM.var("RowH", "46"))
    local warn, critical = tonumber(RM.var("WarnPercent", "80")), tonumber(RM.var("CriticalPercent", "95"))
    local stale_s = tonumber(RM.var("StaleMinutes", "15")) * 60
    local dim, text_color = RM.var("DimColor", "160,160,160"), RM.var("TextColor", "235,235,235")
    local stale_color = RM.var("StaleColor", "253,188,75")
    local row_i, oldest, shown, errors, logins = 0, nil, 0, {}, 0
    for si, p in ipairs(PROVIDERS) do
        local ans = state[p.id]
        local good = last_good[p.id]
        local wanted = RM.var(p.show, "1") ~= "0"
        local rows = ans and ans.ok and ans.rows or (good and good.rows) or nil
        local hidden_login = ans and (not ans.ok) and ans.error == "nologin" and not rows
        if wanted and ans and not hidden_login then
            shown = shown + 1
            logins = logins + 1
            local head = "Head" .. si
            out[#out + 1] = { "show", head, y, p.name }
            y = y + 20
            local at = (ans.ok and ans.at) or (good and good.at) or nil
            local stale = at and (now - at > stale_s)
            local dimmed = not ans.ok
            for _, r in ipairs(rows or {}) do
                if row_i >= MAX_ROWS then break end
                row_i = row_i + 1
                local n = "Row" .. row_i
                local color = level_color(r.percent, warn, critical)
                local pct_color = stale and stale_color or color
                out[#out + 1] = { "row", n, y, r.label, string.format("%d%%", math.floor(r.percent + 0.5)),
                                  math.max(0, math.min(100, r.percent)), color, pct_color,
                                  reset_text(r.resets_at, now), dimmed and dim or text_color, dimmed }
                y = y + row_h
            end
            if not ans.ok then
                local fmt = MESSAGES[ans.error] or ("Error: " .. tostring(ans.error) .. " %s")
                local status = string.format(fmt, p.cli, ans.message or "")
                if ans.error == "nologin" then status = string.format(fmt, p.cli) end
                out[#out + 1] = { "status", "Status" .. si, y, status }
                y = y + 18
            end
            if at and (not oldest or at < oldest) then oldest = at end
            y = y + 6
        else
            out[#out + 1] = { "hide", "Head" .. si }
            out[#out + 1] = { "hide", "Status" .. si }
            if not ans then logins = logins + 1 end
        end
    end
    for i = row_i + 1, MAX_ROWS do out[#out + 1] = { "hiderow", "Row" .. i } end
    local footer
    if shown == 0 then
        local any = state.claude or state.codex
        footer = any and "No Claude Code or Codex login found" or "Loading"
    elseif oldest then
        footer = "Updated " .. os.date("%H:%M", oldest) .. " " .. string.char(0xC2, 0xB7) .. " click to refresh"
    else
        footer = "Waiting for the first answer"
    end
    out[#out + 1] = { "footer", y, footer }
    out[#out + 1] = { "bottom", y + 22 }
    return out
end

function Render()
    for _, item in ipairs(Layout(os.time())) do
        local kind = item[1]
        if kind == "show" then
            RM.bang("!SetOption", item[2], "Y", tostring(item[3]))
            RM.bang("!SetOption", item[2], "Text", item[4])
            RM.bang("!ShowMeter", item[2])
        elseif kind == "hide" then
            RM.bang("!HideMeter", item[2])
        elseif kind == "row" then
            local n, y = item[2], item[3]
            RM.bang("!SetOption", n .. "Label", "Y", tostring(y))
            RM.bang("!SetOption", n .. "Label", "Text", item[4])
            RM.bang("!SetOption", n .. "Label", "FontColor", item[10])
            RM.bang("!SetOption", n .. "Pct", "Y", tostring(y))
            RM.bang("!SetOption", n .. "Pct", "Text", item[5])
            RM.bang("!SetOption", n .. "Pct", "FontColor", item[8])
            RM.bang("!SetOption", n .. "Bar", "Y", tostring(y + 20))
            RM.bang("!SetOption", n .. "Bar", "BarColor", item[7])
            RM.bang("!SetOption", "m" .. n, "Formula", tostring(item[6]))
            RM.bang("!UpdateMeasure", "m" .. n)
            RM.bang("!SetOption", n .. "Reset", "Y", tostring(y + 28))
            RM.bang("!SetOption", n .. "Reset", "Text", item[9])
            for _, part in ipairs({ "Label", "Pct", "Bar", "Reset" }) do RM.bang("!ShowMeter", n .. part) end
        elseif kind == "hiderow" then
            for _, part in ipairs({ "Label", "Pct", "Bar", "Reset" }) do RM.bang("!HideMeter", item[2] .. part) end
        elseif kind == "status" then
            RM.bang("!SetOption", item[2], "Y", tostring(item[3]))
            RM.bang("!SetOption", item[2], "Text", item[4])
            RM.bang("!ShowMeter", item[2])
        elseif kind == "footer" then
            RM.bang("!SetOption", "Footer", "Y", tostring(item[2]))
            RM.bang("!SetOption", "Footer", "Text", item[3])
        elseif kind == "bottom" then
            RM.bang("!SetOption", "Bottom", "Y", tostring(item[2]))
        end
    end
    RM.bang("!UpdateMeter", "*")
    RM.bang("!Redraw")
end

-- ---- Rainmeter's entry points --------------------------------------------------------------------------------
function Initialize()
    for _, p in ipairs(PROVIDERS) do
        RM.bang("!SetOption", p.measure, "Parameter", helper_parameter(p))
    end
end

function Update()
    -- every UpdateDivider ticks: countdowns and staleness move on without a new answer
    if state.claude or state.codex then Render() end
    return 0
end

function Refresh()
    for _, p in ipairs(PROVIDERS) do
        if RM.var(p.show, "1") ~= "0" then RM.bang("!CommandMeasure", p.measure, "Run") end
    end
end

function Answer(provider_id)
    local provider
    for _, p in ipairs(PROVIDERS) do if p.id == provider_id then provider = p end end
    if not provider then return end
    local ans = parse_answer(RM.measure_string(provider.measure))
    if ans.ok then
        ans.at = os.time()
        last_good[provider_id] = ans
    end
    state[provider_id] = ans
    Render()
end

-- for the tests: feed an answer without Rainmeter
function TestAnswer(provider_id, text, at)
    local ans = parse_answer(text)
    if ans.ok then
        ans.at = at
        last_good[provider_id] = ans
    end
    state[provider_id] = ans
end
function TestJson(text) return json.decode(text) end
function TestResetText(iso, now) return reset_text(iso, now) end

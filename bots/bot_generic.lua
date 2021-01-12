local dkjson = require('game/dkjson')
local msgpack = require('bots/msgpack')

local RECV_MSG = 'bots/IPC_recv'
local player_id = GetBot():GetPlayerID()
local faction = GetBot():GetTeam()
local uid = 0
local ipc_prefix = '[IPC]' .. faction .. '.' .. player_id

-- Simply print something we can parse in the logs
--  A: acknowledge
--  S: status        R: Ready
--  E: error
local function send_message(data)
    print(ipc_prefix, dkjson.encode(data))
end

-- Because we are inside a lua VM with limited capabilities
-- We use lua file to receive messages included in the source file
-- Others approach are not doable because
-- Lua 5.1 is embedded into Source 2, we have no library to link against
-- we could try to compile lua 5.1 as a shared library and compile our C package
-- and we might be able to load tcp socket lib but it is assuming require wasnt stripped
local function receive_message()
    local file = loadfile(RECV_MSG)

    if file ~= nil then
        local json_string = file()
        if json_string ~= nil then
            local internal, pos, err = dkjson.decode(json_string, 1, nil)

            if err then
                send_message({E = tostring(err)})
                return nil
            end

            -- Make sure we do not execute a message twice
            local new_uid = internal['uid']
            if new_uid <= uid then
                return nil
            end

            -- Send error when we skipped a message
            if new_uid ~= uid + 1 then
                send_message({
                    E = 'Message skipped (u: ' .. uid .. ') ' .. ' (nu: ' .. new_uid .. ')'
                })
            end

            -- for efficiency we write a single file with all the information
            -- but the bot can only see its command
            local faction_dat = internal[faction]

            if faction_dat ~= nil then
                local player_dat = faction_dat[player_id]

                -- Only update the uid if were able to read the message
                uid = new_uid
                send_message({A = uid})
                return player_dat
            end
        end
    end

    return nil
end

-- From the original dotaservice
local function get_player_info()
    local player_ids = {}
    for _, pid in pairs(GetTeamPlayers(TEAM_RADIANT)) do
        table.insert(player_ids, pid)
    end
    for _, pid in pairs(GetTeamPlayers(TEAM_DIRE)) do
        table.insert(player_ids, pid)
    end
    local players = {}
    for _, pid in pairs(player_ids) do
        local player = {}
        player['id'] = pid
        player['is_bot'] = IsPlayerBot(pid)
        player['team_id'] = GetTeamForPlayer(pid)
        player['hero'] = GetSelectedHeroName(pid)
        table.insert(players, player)
    end
    send_message({P = players})
end

-- A single Game will generate 10 sample for each player
local function delegate_think()
    -- Ready to process a new message
    send_message({S = "R"})

    -- Message uid used to know if we missed a message
    local uid = 0
    local message = receive_message()

    if message ~= nil then
        print(message)
    end
end


local function execute_rpc(message)

end

-- Print the Base game information
get_player_info()

-- Take over the AI entirely
Think = delegate_think
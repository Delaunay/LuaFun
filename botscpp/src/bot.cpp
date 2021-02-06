#include <chrono>
#include <ctime>
#include <thread>

#include <google/protobuf/text_format.h>

#include "utility.h"
#include "protos/dota_gcmessages_common_bot_script.pb.h"


extern "C" void Init(int team_id, void *b, void *c) {
    logfile(team_id);
    print("Init (team:", team_id, ')');
}

// Note that because we only receive our time state
// this is not suited for training because we need both state to compute the
// symmetric reward

// v21 = &a1->CMsgBot[751];
// Observe(libraryTeamID, &a1->CMsgBot[751]);
extern "C" void Observe(int team_id, const CMsgBotWorldState& ws) {
    print("Observe (team:", team_id, ')');

    for (CMsgBotWorldState_Unit unit : ws.units() ) {
        print("PlayerID: ",  unit.player_id());
        print("loc: x=", unit.location().x(), " y=", unit.location().y());
    }
}

// callDynamicallyLoadedLibrary(a1, v28, (__m128)time_delta)
// libraryTeamID = (__int64 *)*(unsigned int *)baseFuncPtr;
// LODWORD(baseFuncPtr) = Act(libraryTeamID, v21);
extern "C" void* Act(int team_id, CMsgBotWorldState &msg) {
    print("Act (team:", team_id, ')');

    std::string s;

    if (google::protobuf::TextFormat::PrintToString(msg, &s)) {
        print("Your message:\n", s);
    } else {
        print("Message not valid (partial content: ", msg.ShortDebugString(), ")");
    }
}

//
extern "C" void Shutdown() {
    print("Shutdown");
}
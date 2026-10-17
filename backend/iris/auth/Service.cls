Class Rakathon.Auth.Service Extends %CSP.REST
{

Parameter HandleCorsRequest = 0;
Parameter UseSession = 0;

XData UrlMap
{
<Routes>
<Route Url="/v1/operation" Method="POST" Call="Operation" />
</Routes>
}

ClassMethod Authorized() As %Boolean
{
    if $namespace'="USER" { quit 0 }
    if $get(^RakathonAuthConfig("enabled"))'=1 { quit 0 }
    set principal=$get(^RakathonAuthConfig("serviceUser"))
    if (principal="")!(principal="UnknownUser")!($username'=principal) { quit 0 }
    quit $SYSTEM.Security.Check("RakathonAuthService","U")
}

ClassMethod Operation() As %Status
{
    set %response.ContentType="application/json"
    do %response.SetHeader("Cache-Control","no-store")
    set response={"v":1,"ok":false,"error":"store_unavailable"},locked=0,started=0
    try {
        if '..Authorized() {
            set %response.Status="403 Forbidden"
        } else {
            if (%request.Method'="POST")!($piece(%request.ContentType,";",1)'="application/json") { do ##class(Rakathon.Auth.Contract).Bad() }
            if %request.Content.Size>16384 { do ##class(Rakathon.Auth.Contract).Bad() }
            set raw=%request.Content.Read(16385)
            if '%request.Content.AtEnd { do ##class(Rakathon.Auth.Contract).Bad() }
            set req=##class(Rakathon.Auth.StrictJSON).Parse(raw)
            do ##class(Rakathon.Auth.Contract).Request(req)
            lock +^RakathonAuthLocks("USER"):2
            if '$test { do ##class(Rakathon.Auth.SQL).Fail() }
            set locked=1
            if $tlevel'=0 { do ##class(Rakathon.Auth.SQL).Fail() }
            tstart
            set started=1,result="",kind="null"
            if req.op="rate_reserve" {
                do ##class(Rakathon.Auth.Rate).Reserve(req.args)
            } elseif $listfind($listbuild("create_user","update_user","get_user_by_id","get_user_by_index"),req.op) {
                do ##class(Rakathon.Auth.Users).Dispatch(req.op,req.args,.result,.kind)
            } else {
                do ##class(Rakathon.Auth.Sessions).Dispatch(req.op,req.args,.result,.kind)
            }
            set response={"v":1,"ok":true}
            do response.%Set("result",result,kind)
            // Serialize and bound before committing, never return a partial profile.
            set encoded=response.%ToJSON()
            if $length(encoded)>16384 { do ##class(Rakathon.Auth.SQL).Fail() }
            tcommit
            set started=0
        }
    } catch ex {
        if started {
            if $tlevel>0 { trollback 1 }
            set started=0
        }
        set code="store_unavailable"
        if $listfind($listbuild("bad_payload","duplicate_id","rate_limited"),ex.Name) { set code=ex.Name }
        set response={"v":1,"ok":false}
        do response.%Set("error",code,"string")
    }
    if locked { lock -^RakathonAuthLocks("USER") }
    write response.%ToJSON()
    quit $SYSTEM.Status.OK()
}
}

Class Rakathon.Auth.Sessions Extends %RegisteredObject
{

ClassMethod Row(rs) As %DynamicObject
{
    set obj={}
    for i=1:1:3 {
        set key=$piece("token_hash,user_id,role",",",i)
        do obj.%Set(key,rs.%Get(key),"string")
    }
    for i=1:1:4 {
        set key=$piece("auth_version,created_at,last_seen,expires_at",",",i)
        do obj.%Set(key,+rs.%Get(key),"number")
    }
    do ##class(Rakathon.Auth.Contract).Session(obj)
    quit obj
}

ClassMethod Create(rec)
{
    set user=##class(Rakathon.Auth.Users).Get("user_id",rec.user_id)
    if '$isobject(user) { do ##class(Rakathon.Auth.SQL).Fail() }
    if 'user.active!(user.auth_version'=rec.auth_version)!(user.role'=rec.role) { do ##class(Rakathon.Auth.SQL).Fail() }
    set count=##class(Rakathon.Auth.SQL).Run("SELECT COUNT(*) AS total FROM FSB.AuthSessions WHERE user_id=?",[(rec.user_id)])
    if '##class(Rakathon.Auth.SQL).One(count) { do ##class(Rakathon.Auth.SQL).Fail() }
    if count.%Get("total")>=32 { do ##class(Rakathon.Auth.SQL).Fail() }
    set params=[(rec.token_hash),(rec.user_id),(rec.auth_version),(rec.role),(rec.created_at),(rec.last_seen),(rec.expires_at)]
    set rs=##class(Rakathon.Auth.SQL).Run("INSERT INTO FSB.AuthSessions (token_hash,user_id,auth_version,role,created_at,last_seen,expires_at) VALUES (?,?,?,?,?,?,?)",params)
    if ##class(Rakathon.Auth.SQL).Changed(rs)'=1 { do ##class(Rakathon.Auth.SQL).Fail() }
}

ClassMethod Prune(args, expired As %Boolean)
{
    // Fixed query bounds; the requested limit is applied inside this transaction.
    if expired {
        set rs=##class(Rakathon.Auth.SQL).Run("SELECT TOP 1000 token_hash,last_seen FROM FSB.AuthSessions WHERE expires_at<=? ORDER BY expires_at,token_hash",[(args.now)])
    } else {
        set rs=##class(Rakathon.Auth.SQL).Run("SELECT TOP 1033 token_hash,last_seen FROM FSB.AuthSessions WHERE user_id=? ORDER BY last_seen DESC,token_hash DESC",[(args.user_id)])
    }
    set rows=[],seen=0
    while ##class(Rakathon.Auth.SQL).One(rs) {
        set seen=seen+1
        if expired { set remove=(seen<=args.limit) } else { set remove=(seen>args.keep) }
        if remove {
            do rows.%Push([(rs.%Get("token_hash")),(+rs.%Get("last_seen"))])
        }
    }
    for i=0:1:rows.%Size()-1 {
        set row=rows.%Get(i)
        if expired {
            set del=##class(Rakathon.Auth.SQL).Run("DELETE FROM FSB.AuthSessions WHERE token_hash=? AND last_seen=? AND expires_at<=?",[(row.%Get(0)),(row.%Get(1)),(args.now)])
        } else {
            set del=##class(Rakathon.Auth.SQL).Run("DELETE FROM FSB.AuthSessions WHERE token_hash=? AND last_seen=? AND user_id=?",[(row.%Get(0)),(row.%Get(1)),(args.user_id)])
        }
        set ignored=##class(Rakathon.Auth.SQL).Changed(del)
    }
}

ClassMethod Dispatch(op As %String, args, ByRef result, ByRef kind)
{
    if op="create_session" { do ..Create(args.record) quit }
    if op="get_session" {
        set rs=##class(Rakathon.Auth.SQL).Run("SELECT TOP 1 token_hash,user_id,auth_version,role,created_at,last_seen,expires_at FROM FSB.AuthSessions WHERE token_hash=?",[(args.token_hash)])
        if ##class(Rakathon.Auth.SQL).One(rs) { set result=..Row(rs),kind="object" }
        quit
    }
    if op="cas_last_seen" {
        set rs=##class(Rakathon.Auth.SQL).Run("UPDATE FSB.AuthSessions SET last_seen=? WHERE token_hash=? AND last_seen=? AND expires_at>?",[(args.new),(args.token_hash),(args.old),(args.new)])
        set result=(##class(Rakathon.Auth.SQL).Changed(rs)=1),kind="boolean"
        quit
    }
    if op="delete_session" {
        set rs=##class(Rakathon.Auth.SQL).Run("DELETE FROM FSB.AuthSessions WHERE token_hash=?",[(args.token_hash)])
        set ignored=##class(Rakathon.Auth.SQL).Changed(rs)
        quit
    }
    if op="count_user_sessions" {
        set rs=##class(Rakathon.Auth.SQL).Run("SELECT COUNT(*) AS total FROM FSB.AuthSessions WHERE user_id=?",[(args.user_id)])
        if '##class(Rakathon.Auth.SQL).One(rs) { do ##class(Rakathon.Auth.SQL).Fail() }
        set result=+rs.%Get("total"),kind="number"
        quit
    }
    if op="revoke_user_sessions" {
        set rs=##class(Rakathon.Auth.SQL).Run("DELETE FROM FSB.AuthSessions WHERE user_id=?",[(args.user_id)])
        set ignored=##class(Rakathon.Auth.SQL).Changed(rs,2147483647)
        quit
    }
    if (op="prune_user_sessions")!(op="prune_expired_sessions") {
        do ..Prune(args,(op="prune_expired_sessions"))
        quit
    }
    do ##class(Rakathon.Auth.Contract).Bad()
}
}

Class Rakathon.Auth.Users Extends %RegisteredObject
{

ClassMethod Row(rs) As %DynamicObject
{
    set obj={}
    set fields="user_id,username_index,password_hash,enc_nonce,enc_ct,key_id,role"
    for i=1:1:$length(fields,",") {
        set key=$piece(fields,",",i)
        do obj.%Set(key,rs.%Get(key),"string")
    }
    do obj.%Set("active",(rs.%Get("active")="1"),"boolean")
    set fields="auth_version,created_at,updated_at"
    for i=1:1:$length(fields,",") {
        set key=$piece(fields,",",i)
        do obj.%Set(key,+rs.%Get(key),"number")
    }
    do ##class(Rakathon.Auth.Contract).User(obj)
    quit obj
}

ClassMethod Get(key As %String, val As %String)
{
    // Column choices are internal constants, never taken from a request.
    if (key'="user_id")&&(key'="username_index") { do ##class(Rakathon.Auth.SQL).Fail() }
    set sql="SELECT TOP 1 user_id,username_index,password_hash,enc_nonce,enc_ct,key_id,role,active,auth_version,created_at,updated_at FROM FSB.AuthUsers WHERE "_key_" = ?"
    set rs=##class(Rakathon.Auth.SQL).Run(sql,[(val)])
    if '##class(Rakathon.Auth.SQL).One(rs) { quit "" }
    quit ..Row(rs)
}

ClassMethod Create(rec)
{
    set params=[(rec.user_id),(rec.username_index),(rec.password_hash),(rec.enc_nonce),(rec.enc_ct),(rec.key_id),(rec.role),($select(rec.active:"1",1:"0")),(rec.auth_version),(rec.created_at),(rec.updated_at)]
    if rec.auth_version'=1 { do ##class(Rakathon.Auth.Contract).Bad() }
    set rs=##class(Rakathon.Auth.SQL).Run("INSERT INTO FSB.AuthUsers (user_id,username_index,password_hash,enc_nonce,enc_ct,key_id,role,active,auth_version,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",params,1)
    if rs.%SQLCODE=-119 { do ##class(Rakathon.Auth.SQL).Fail("duplicate_id") }
    if ##class(Rakathon.Auth.SQL).Changed(rs)'=1 { do ##class(Rakathon.Auth.SQL).Fail() }
}

ClassMethod Update(rec)
{
    set current=..Get("user_id",rec.user_id)
    if '$isobject(current) { do ##class(Rakathon.Auth.SQL).Fail() }
    set unchanged="username_index,enc_nonce,enc_ct,key_id,created_at"
    for i=1:1:$length(unchanged,",") {
        set key=$piece(unchanged,",",i)
        if rec.%Get(key)'=current.%Get(key) { do ##class(Rakathon.Auth.SQL).Fail() }
    }
    if (rec.auth_version<current.auth_version)!(rec.auth_version>current.auth_version+1) { do ##class(Rakathon.Auth.SQL).Fail() }
    if rec.updated_at<current.updated_at { do ##class(Rakathon.Auth.SQL).Fail() }
    set advance=(rec.auth_version>current.auth_version)
    if 'advance,((rec.role'=current.role)!(rec.active'=current.active)) { do ##class(Rakathon.Auth.SQL).Fail() }
    set params=[(rec.password_hash),(rec.role),($select(rec.active:"1",1:"0")),(rec.auth_version),(rec.updated_at),(rec.user_id),(current.auth_version),(current.updated_at)]
    set rs=##class(Rakathon.Auth.SQL).Run("UPDATE FSB.AuthUsers SET password_hash=?,role=?,active=?,auth_version=?,updated_at=? WHERE user_id=? AND auth_version=? AND updated_at=?",params)
    if ##class(Rakathon.Auth.SQL).Changed(rs)'=1 { do ##class(Rakathon.Auth.SQL).Fail() }
    if advance {
        set rs=##class(Rakathon.Auth.SQL).Run("DELETE FROM FSB.AuthSessions WHERE user_id=?",[(rec.user_id)])
        set ignored=##class(Rakathon.Auth.SQL).Changed(rs,2147483647)
    }
}

ClassMethod Dispatch(op As %String, args, ByRef result, ByRef kind)
{
    if op="create_user" { do ..Create(args.record) quit }
    if op="update_user" { do ..Update(args.record) quit }
    set key=$select(op="get_user_by_id":"user_id",1:"username_index")
    set obj=..Get(key,args.%Get(key))
    if $isobject(obj) { set result=obj,kind="object" }
}
}

Class Rakathon.Auth.Contract Extends %RegisteredObject
{

ClassMethod Bad()
{
    do ##class(Rakathon.Auth.StrictJSON).Bad()
}

ClassMethod Fields(op As %String) As %String
{
    if (op="create_user")!(op="update_user")!(op="create_session") { quit "record" }
    if op="get_user_by_index" { quit "username_index" }
    if (op="get_user_by_id")!(op="count_user_sessions")!(op="revoke_user_sessions") { quit "user_id" }
    if (op="get_session")!(op="delete_session") { quit "token_hash" }
    if op="cas_last_seen" { quit "token_hash,old,new" }
    if op="prune_user_sessions" { quit "user_id,keep" }
    if op="prune_expired_sessions" { quit "now,limit" }
    if op="rate_reserve" { quit "account_key,now,account_limit,account_window,global_limit,global_window" }
    quit ""
}

ClassMethod Shape(obj, fields As %String)
{
    if '$isobject(obj) { do ..Bad() }
    if 'obj.%IsA("%Library.DynamicObject") { do ..Bad() }
    if obj.%Size()'=$length(fields,",") { do ..Bad() }
    for i=1:1:$length(fields,",") {
        if 'obj.%IsDefined($piece(fields,",",i)) { do ..Bad() }
    }
}

ClassMethod Number(obj, key As %String, min As %Integer = 0, max As %Numeric = 253402300799)
{
    if obj.%GetTypeOf(key)'="number" { do ..Bad() }
    set val=obj.%Get(key)
    if val'?1.N { do ..Bad() }
    if (val<min)!(val>max) { do ..Bad() }
}

ClassMethod Text(obj, key As %String, max As %Integer)
{
    if obj.%GetTypeOf(key)'="string" { do ..Bad() }
    set val=obj.%Get(key)
    if ($length(val)=0)!($length(val)>max) { do ..Bad() }
    for i=1:1:$length(val) { if ($ascii(val,i)<32)!($ascii(val,i)>126) { do ..Bad() } }
}

ClassMethod Hex(obj, key As %String, size As %Integer)
{
    do ..Text(obj,key,size)
    set val=obj.%Get(key)
    if ($length(val)'=size)!($translate(val,"0123456789abcdef","")'="") { do ..Bad() }
}

ClassMethod Base64(obj, key As %String, min As %Integer, max As %Integer)
{
    do ..Text(obj,key,1024)
    set val=obj.%Get(key),size=$length(val),alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    if size#4 { do ..Bad() }
    set pad=0
    if $extract(val,size)="=" { set pad=1 }
    if $extract(val,size-1,size)="==" { set pad=2 }
    set core=$extract(val,1,size-pad),decoded=(size\4)*3-pad
    if (decoded<min)!(decoded>max)!($translate(core,alphabet,"")'="") { do ..Bad() }
    set last=$find(alphabet,$extract(core,*))-2
    if (pad=1),(last#4) { do ..Bad() }
    if (pad=2),(last#16) { do ..Bad() }
}

ClassMethod Role(obj)
{
    do ..Text(obj,"role",16)
    if '$listfind($listbuild("admin","coordinator","clinician","viewer"),obj.role) { do ..Bad() }
}

ClassMethod User(obj)
{
    do ..Shape(obj,"user_id,username_index,password_hash,enc_nonce,enc_ct,key_id,role,active,auth_version,created_at,updated_at")
    do ..Hex(obj,"user_id",32),..Hex(obj,"username_index",64)
    do ..Text(obj,"password_hash",512)
    if $extract(obj.password_hash,1,10)'="$argon2id$" { do ..Bad() }
    if $translate(obj.password_hash,"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789$=,+/.-","")'="" { do ..Bad() }
    do ..Base64(obj,"enc_nonce",12,12),..Base64(obj,"enc_ct",17,768)
    do ..Text(obj,"key_id",64),..Role(obj)
    if $translate(obj.key_id,"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-","")'="" { do ..Bad() }
    if obj.%GetTypeOf("active")'="boolean" { do ..Bad() }
    do ..Number(obj,"auth_version",1,2147483647),..Number(obj,"created_at"),..Number(obj,"updated_at")
    if obj.updated_at<obj.created_at { do ..Bad() }
}

ClassMethod Session(obj)
{
    do ..Shape(obj,"token_hash,user_id,auth_version,role,created_at,last_seen,expires_at")
    do ..Hex(obj,"token_hash",64),..Hex(obj,"user_id",32),..Role(obj)
    do ..Number(obj,"auth_version",1,2147483647),..Number(obj,"created_at"),..Number(obj,"last_seen"),..Number(obj,"expires_at")
    if (obj.last_seen<obj.created_at)!(obj.expires_at<=obj.last_seen) { do ..Bad() }
}

ClassMethod Request(req)
{
    do ..Shape(req,"v,op,args"),..Number(req,"v",1,1),..Text(req,"op",32)
    set fields=..Fields(req.op)
    if fields="" { do ..Bad() }
    if req.%GetTypeOf("args")'="object" { do ..Bad() }
    set args=req.args
    do ..Shape(args,fields)
    for i=1:1:$length(fields,",") {
        set key=$piece(fields,",",i)
        if key="record" {
            if req.op="create_session" { do ..Session(args.record) } else { do ..User(args.record) }
        } elseif key="user_id" { do ..Hex(args,key,32)
        } elseif (key="token_hash")!(key="username_index")!(key="account_key") { do ..Hex(args,key,64)
        } elseif (key="account_limit")!(key="global_limit") { do ..Number(args,key,1,10000)
        } elseif (key="account_window")!(key="global_window") { do ..Number(args,key,1,86400)
        } elseif key="keep" { do ..Number(args,key,0,32)
        } elseif key="limit" { do ..Number(args,key,1,1000)
        } else { do ..Number(args,key) }
    }
    if req.op="cas_last_seen",args.new<args.old { do ..Bad() }
}
}

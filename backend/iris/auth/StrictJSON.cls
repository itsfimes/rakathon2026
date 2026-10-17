Class Rakathon.Auth.StrictJSON Extends %RegisteredObject
{

ClassMethod Bad()
{
    set ex=##class(%Exception.General).%New()
    set ex.Name="bad_payload"
    throw ex
}

ClassMethod Space(raw As %String, ByRef pos As %Integer)
{
    while pos<=$length(raw),$find(" "_$char(9,10,13),$extract(raw,pos)) { set pos=pos+1 }
}

ClassMethod String(raw As %String, ByRef pos As %Integer) As %String
{
    if $extract(raw,pos)'=$char(34) { do ..Bad() }
    set start=pos,pos=pos+1,closed=0
    while pos<=$length(raw) {
        set ch=$extract(raw,pos),pos=pos+1
        if ch=$char(34) { set closed=1 quit }
        if $ascii(ch)<32 { do ..Bad() }
        if ch=$char(92) {
            set esc=$extract(raw,pos),pos=pos+1
            if esc="u" {
                set hex=$extract(raw,pos,pos+3)
                if $length(hex)'=4!($translate(hex,"0123456789abcdefABCDEF","")'="") { do ..Bad() }
                set pos=pos+4
            } elseif '$find($char(34,92)_"/bfnrt",esc) { do ..Bad() }
        }
    }
    if 'closed { do ..Bad() }
    set token=$extract(raw,start,pos-1)
    set arr=##class(%DynamicArray).%FromJSON("["_token_"]")
    quit arr.%Get(0)
}

ClassMethod Object(raw As %String, ByRef pos As %Integer, depth As %Integer)
{
    if depth>3 { do ..Bad() }
    if $extract(raw,pos)'="{" { do ..Bad() }
    set pos=pos+1,count=0
    do ..Space(raw,.pos)
    if $extract(raw,pos)="}" { set pos=pos+1 quit }
    for {
        do ..Space(raw,.pos)
        set key=..String(raw,.pos)
        if $data(seen(key)) { do ..Bad() }
        set seen(key)=1,count=count+1
        if count>16 { do ..Bad() }
        do ..Space(raw,.pos)
        if $extract(raw,pos)'=":" { do ..Bad() }
        set pos=pos+1
        do ..Value(raw,.pos,depth+1)
        do ..Space(raw,.pos)
        set ch=$extract(raw,pos),pos=pos+1
        if ch="}" { quit }
        if ch'="," { do ..Bad() }
    }
}

ClassMethod Value(raw As %String, ByRef pos As %Integer, depth As %Integer)
{
    do ..Space(raw,.pos)
    set ch=$extract(raw,pos)
    if ch="{" { do ..Object(raw,.pos,depth) quit }
    if ch=$char(34) { set ignored=..String(raw,.pos) quit }
    set start=pos
    while pos<=$length(raw),'$find(",} "_$char(9,10,13),$extract(raw,pos)) { set pos=pos+1 }
    set token=$extract(raw,start,pos-1)
    if (token="true")!(token="false")!(token="null") { quit }
    if token'?1.N { do ..Bad() }
    if $length(token)>1,$extract(token,1)="0" { do ..Bad() }
    if $length(token)>12 { do ..Bad() }
}

ClassMethod Parse(raw As %String) As %DynamicObject
{
    if ($length(raw)=0)!($length(raw)>16384) { do ..Bad() }
    for i=1:1:$length(raw) { if $ascii(raw,i)>127 { do ..Bad() } }
    set pos=1
    do ..Space(raw,.pos)
    do ..Object(raw,.pos,1)
    do ..Space(raw,.pos)
    if pos'=$length(raw)+1 { do ..Bad() }
    quit ##class(%DynamicObject).%FromJSON(raw)
}
}

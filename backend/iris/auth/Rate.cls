Class Rakathon.Auth.Rate Extends %RegisteredObject
{

ClassMethod Claim(scope As %String, key As %String, limit As %Integer, now As %Numeric, cutoff As %Numeric, reservation As %String) As %Boolean
{
    set claimed=0
    for slot=0:1:limit-1 {
        set rs=##class(Rakathon.Auth.SQL).Run("UPDATE FSB.AuthRate SET ts=?,reservation_id=? WHERE scope=? AND key=? AND slot=? AND ts<=?",[(now),(reservation),(scope),(key),(slot),(cutoff)])
        if ##class(Rakathon.Auth.SQL).Changed(rs)=1 { set claimed=1 quit }
        set rs=##class(Rakathon.Auth.SQL).Run("INSERT INTO FSB.AuthRate (scope,key,slot,ts,reservation_id) VALUES (?,?,?,?,?)",[(scope),(key),(slot),(now),(reservation)],1)
        if rs.%SQLCODE=-119 { continue }
        if ##class(Rakathon.Auth.SQL).Changed(rs)'=1 { do ##class(Rakathon.Auth.SQL).Fail() }
        set claimed=1
        quit
    }
    quit claimed
}

ClassMethod Reserve(args)
{
    // The caller owns one transaction and a finite server-side named lock.
    // A denied global claim rolls back the account claim in that transaction.
    set reservation=$translate($SYSTEM.Util.CreateGUID(),"-","")
    if '..Claim("acct",args.account_key,args.account_limit,args.now,args.now-args.account_window,reservation) {
        do ##class(Rakathon.Auth.SQL).Fail("rate_limited")
    }
    if '..Claim("glob","g",args.global_limit,args.now,args.now-args.global_window,reservation) {
        do ##class(Rakathon.Auth.SQL).Fail("rate_limited")
    }
}
}

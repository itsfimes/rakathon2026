Class Rakathon.Auth.SQL Extends %RegisteredObject
{

ClassMethod Fail(code As %String = "store_unavailable")
{
    set ex=##class(%Exception.General).%New()
    set ex.Name=code
    throw ex
}

ClassMethod Run(sql As %String, params As %DynamicArray, duplicate As %Boolean = 0) As %SQL.StatementResult
{
    set stmt=##class(%SQL.Statement).%New(),sc=stmt.%Prepare(sql)
    if $SYSTEM.Status.IsError(sc) { do ..Fail() }
    set args=params.%Size()
    for i=0:1:args-1 { set args(i+1)=params.%Get(i) }
    set result=stmt.%Execute(args...)
    if result.%SQLCODE<0 {
        if '(duplicate&&(result.%SQLCODE=-119)) { do ..Fail() }
    }
    quit result
}

ClassMethod One(result) As %Boolean
{
    set found=result.%Next()
    if result.%SQLCODE<0 { do ..Fail() }
    quit found
}

ClassMethod Changed(result, max As %Integer = 1) As %Integer
{
    if (result.%ROWCOUNT<0)!(result.%ROWCOUNT>max) { do ..Fail() }
    quit result.%ROWCOUNT
}
}

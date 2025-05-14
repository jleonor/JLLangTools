@echo off
curl -v ^
  -X POST ^
  "http://localhost:6001/transcribe" ^
  --data-urlencode "youtube_url=https://www.youtube.com/playlist?list=PLrqHrGoMJdTQdbChS4itHS3887uJaXDt8" ^
  --data "lang_key=en" ^
  --header "Content-Type: application/x-www-form-urlencoded" ^
  --header "Accept: application/json"

#pragma once
#include <cstdint>
#include <cstdio>
#include <cstring>
namespace tunnel {
inline std::uint32_t utcSeconds(const char* text) {
  if(!text||std::strlen(text)!=20)return 0;
  unsigned year,month,day,hour,minute,second;char end=0;
  if(std::sscanf(text,"%4u-%2u-%2uT%2u:%2u:%2u%c",&year,&month,&day,&hour,&minute,&second,&end)!=7||end!='Z'||year<2024||year>2105||month<1||month>12||day<1||hour>23||minute>59||second>59)return 0;
  const bool leap=year%4==0&&(year%100!=0||year%400==0);
  const unsigned days[]={31,28,31,30,31,30,31,31,30,31,30,31};
  if(day>days[month-1]+unsigned(month==2&&leap))return 0;
  std::uint64_t count=0;
  for(unsigned y=1970;y<year;++y)count+=365+unsigned(y%4==0&&(y%100!=0||y%400==0));
  for(unsigned m=1;m<month;++m)count+=days[m-1]+unsigned(m==2&&leap);
  return std::uint32_t(((count+day-1)*24+hour)*3600+minute*60+second);
}
}

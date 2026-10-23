// Fixed-order diagnostic only. Expected timestamps are loaded AFTER solving;
// they never appear among the graph's release constants or edge weights.
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <ctime>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>
template<class T>void read(std::ifstream& f,std::vector<T>& x){f.read(reinterpret_cast<char*>(x.data()),std::streamsize(x.size()*sizeof(T)));if(!f)throw std::runtime_error("truncated graph");}
int main(int argc,char**argv){try{
  const auto cpu_start=std::clock();
  if(argc!=4)throw std::runtime_error("graph_solve GRAPH EXPECTED REPEATS");
  std::ifstream file(argv[1],std::ios::binary);uint64_t n=0,m=0;
  file.read(reinterpret_cast<char*>(&n),8);file.read(reinterpret_cast<char*>(&m),8);
  std::vector<int64_t> release(n),answer(n);std::vector<uint64_t> offset(n+1);
  std::vector<uint32_t> pred(m);std::vector<int32_t> delay(m);
  read(file,release);read(file,offset);read(file,pred);read(file,delay);
  const int repeat=std::stoi(argv[3]);std::vector<double> samples;uint64_t checksum=0;
  for(int trial=0;trial<repeat;++trial){
    auto start=std::chrono::steady_clock::now();
    for(uint64_t i=0;i<n;++i){auto t=release[i];for(uint64_t e=offset[i];e<offset[i+1];++e){if(pred[e]>=i)throw std::runtime_error("not a DAG");t=std::max(t,answer[pred[e]]+delay[e]);}answer[i]=t;}
    samples.push_back(std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count());
    checksum+=uint64_t(answer.back());
  }
  std::ifstream truth(argv[2],std::ios::binary);std::vector<int64_t> expected(n);read(truth,expected);
  uint64_t mismatches=0;int64_t worst=0;uint64_t first=n;
  for(uint64_t i=0;i<n;++i)if(answer[i]!=expected[i]){++mismatches;first=std::min(first,i);worst=std::max(worst,std::abs(answer[i]-expected[i]));}
  std::ofstream prediction(std::string(argv[1])+".predicted.bin",std::ios::binary);
  prediction.write(reinterpret_cast<const char*>(answer.data()),std::streamsize(answer.size()*sizeof(int64_t)));
  std::sort(samples.begin(),samples.end());
  std::cout<<"{\"nodes\":"<<n<<",\"edges\":"<<m<<",\"solve_median_seconds\":"<<samples[samples.size()/2]
    <<",\"process_cpu_seconds\":"<<double(std::clock()-cpu_start)/CLOCKS_PER_SEC
    <<",\"mismatches\":"<<mismatches<<",\"max_absolute_cycle_error\":"<<worst
    <<",\"first_mismatch_node\":"<<first<<",\"checksum\":"<<checksum<<"}\n";
  return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}

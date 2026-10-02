#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <numeric>
#include <optional>
#include <set>
#include <random>
#include <cstdio>
#include <sstream>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

using namespace std;

namespace {
const vector<string> kFeatureColumns = {
    "month", "OficinaACNUR", "Demographics.HH.Head",
    "Demographics.Language", "Demographics.Profiles",
    "Demographics.Documentation", "Needs_and_Coping.BasicNeeds",
    "Needs_and_Coping.Housing", "Needs_and_Coping.Neg.mechanism",
    "Needs_and_Coping.Dependency", "NumIntegrantes", "dependencyCategory",
    "FemaleHeadedHousehold", "CuidadorSolo", "HablaEspanol",
    "Analfabeta_si", "ScoreCOMAR_PIL", "ScoreIntenciones", "ScoreDuplicidad"
};
const vector<string> kNumericColumns = {
    "Demographics.HH.Head", "Demographics.Language", "Demographics.Profiles",
    "Demographics.Documentation", "Needs_and_Coping.BasicNeeds",
    "Needs_and_Coping.Housing", "Needs_and_Coping.Neg.mechanism",
    "Needs_and_Coping.Dependency", "NumIntegrantes"
};
const vector<string> kScoreColumns = {
    "ScoreCOMAR_PIL", "ScoreIntenciones", "ScoreDuplicidad"
};

string trim(const string& s) {
    const auto a = s.find_first_not_of(" \t\r\n");
    if (a == string::npos) return "";
    const auto b = s.find_last_not_of(" \t\r\n");
    return s.substr(a, b - a + 1);
}

void stripUtf8Bom(vector<string>& headers) {
    if (!headers.empty() && headers[0].size() >= 3 &&
        static_cast<unsigned char>(headers[0][0]) == 0xEF &&
        static_cast<unsigned char>(headers[0][1]) == 0xBB &&
        static_cast<unsigned char>(headers[0][2]) == 0xBF)
        headers[0].erase(0, 3);
}

// No label is returned when a separate AI recommendation is unavailable.
optional<int> aiErrorLabel(const string& recommendation, const string& reference) {
    if (recommendation != "INCLUSION" && recommendation != "EXCLUSION") return nullopt;
    if (reference != "INCLUSION" && reference != "EXCLUSION") return nullopt;
    return recommendation == reference ? 0 : 1;
}

vector<string> parseCsvLine(const string& line) {
    vector<string> result;
    string field;
    bool quoted = false;
    for (size_t i = 0; i < line.size(); ++i) {
        const char c = line[i];
        if (c == '"') {
            if (quoted && i + 1 < line.size() && line[i + 1] == '"') {
                field += '"'; ++i;
            } else quoted = !quoted;
        } else if (c == ',' && !quoted) {
            result.push_back(field); field.clear();
        } else field += c;
    }
    result.push_back(field);
    return result;
}

string csvEscape(const string& s) {
    if (s.find_first_of(",\"\r\n") == string::npos) return s;
    string out = "\"";
    for (char c : s) { if (c == '"') out += '"'; out += c; }
    return out + '"';
}

bool number(const string& s, double& x) {
    const string t = trim(s);
    if (t.empty()) return false;
    try {
        size_t used = 0;
        x = stod(t, &used);
        return used == t.size() && isfinite(x);
    } catch (...) { return false; }
}

string scoreCategory(const string& text) {
    const string raw=trim(text);
    if(raw.empty()) return "MISSING_NOT_APPLICABLE";
    double value;
    if(!number(raw,value)) return "OTHER_VALUE:"+raw;
    if(value==-500.0) return "FLAG_-500";
    if(value==500.0) return "FLAG_+500";
    if(value==0.0) return "ZERO";
    return "OTHER_NUMERIC:"+raw;
}

double sigmoid(double z) {
    if (z >= 0) { const double e = exp(-z); return 1.0 / (1.0 + e); }
    const double e = exp(z); return e / (1.0 + e);
}

struct Row {
    vector<string> cells;
    string month;
    string target;
    string aiRecommendation;
    int aiErrorLabel = -1;
    int y = 0; // 1 = recorded INCLUSION, 0 = recorded EXCLUSION
    bool anomaly = false;
    bool conflict = false;
    size_t originalRowId = 0;
};

struct Encoder {
    vector<string> names;
    vector<double> means, scales;
    vector<unordered_map<string, size_t>> cats;
    vector<vector<double>> x;

    Encoder(const vector<Row>& rows, const unordered_map<string, size_t>& col) {
        vector<string> headers;
        for (const string& n : kFeatureColumns) {
            auto it = col.find(n);
            if (it == col.end()) throw runtime_error("Missing predictor column: " + n);
            headers.push_back(n);
        }
        means.assign(headers.size(), 0.0);
        scales.assign(headers.size(), 1.0);
        cats.resize(headers.size());
        for (size_t j = 0; j < headers.size(); ++j) {
            const string& name = headers[j];
            const size_t c = col.at(name);
            if (find(kNumericColumns.begin(), kNumericColumns.end(), name) != kNumericColumns.end()) {
                vector<double> vals;
                for (const auto& r : rows) { double v; if (number(r.cells[c], v)) vals.push_back(v); }
                const double mean = vals.empty() ? 0.0 : accumulate(vals.begin(), vals.end(), 0.0) / vals.size();
                double var = 0.0;
                for (double v : vals) var += (v - mean) * (v - mean);
                const double sd = vals.size() < 2 ? 1.0 : sqrt(var / vals.size());
                const double scale = sd > 1e-12 ? sd : 1.0;
                names.push_back(name);
                names.push_back(name + " [missing]");
                means[j] = mean; scales[j] = scale;
            } else if (find(kScoreColumns.begin(), kScoreColumns.end(), name) != kScoreColumns.end()) {
                set<string> levels;
                for (const auto& r : rows) {
                    levels.insert(scoreCategory(r.cells[c]));
                }
                levels.insert("UNKNOWN");
                unordered_map<string, size_t> mapping;
                for (const auto& level : levels) {
                    mapping[level] = names.size();
                    names.push_back(name + "=" + level);
                }
                cats[j] = std::move(mapping);
            } else {
                set<string> levels;
                for (const auto& r : rows) {
                    const string value = trim(r.cells[c]);
                    levels.insert(value.empty() ? "MISSING_NOT_APPLICABLE" : value);
                }
                levels.insert("UNKNOWN");
                unordered_map<string, size_t> mapping;
                for (const auto& level : levels) {
                    mapping[level] = names.size();
                    names.push_back(name + "=" + level);
                }
                cats[j] = std::move(mapping);
            }
        }
        x.assign(rows.size(), vector<double>(names.size(), 0.0));
        size_t feature = 0;
        for (size_t headerIndex = 0; headerIndex < headers.size(); ++headerIndex) {
            const string& name = headers[headerIndex];
            const size_t c = col.at(name);
            if (find(kNumericColumns.begin(), kNumericColumns.end(), name) != kNumericColumns.end()) {
                const double mean = means[headerIndex], scale = scales[headerIndex];
                for (size_t i = 0; i < rows.size(); ++i) {
                    double v;
                    if (number(rows[i].cells[c], v)) x[i][feature] = (v - mean) / scale;
                    else x[i][feature + 1] = 1.0;
                }
                feature += 2;
            } else {
                const auto& mapping = cats[headerIndex];
                for (size_t i = 0; i < rows.size(); ++i) {
                    const string raw = trim(rows[i].cells[c]);
                    string key;
                    if (find(kScoreColumns.begin(), kScoreColumns.end(), name) != kScoreColumns.end()) {
                        key = scoreCategory(raw);
                    } else key = raw.empty() ? "MISSING_NOT_APPLICABLE" : raw;
                    auto it = mapping.find(key);
                    if (it == mapping.end()) it = mapping.find("UNKNOWN");
                    x[i][it->second] = 1.0;
                }
                feature += mapping.size();
            }
        }
    }
};

struct Model { vector<double> w; double b = 0; };

Model trainLogistic(const vector<vector<double>>& x, const vector<int>& y,
                    const vector<size_t>& ids, double lambda = 0.02) {
    Model m; if (ids.empty()) return m;
    m.w.assign(x[0].size(), 0.0);
    const double rate = 0.08;
    for (int epoch = 0; epoch < 300; ++epoch) {
        vector<double> grad(m.w.size(), 0.0); double gb = 0.0;
        for (size_t i : ids) {
            double z = m.b;
            for (size_t j = 0; j < m.w.size(); ++j) if (x[i][j] != 0.0) z += m.w[j] * x[i][j];
            const double e = sigmoid(z) - y[i];
            gb += e;
            for (size_t j = 0; j < m.w.size(); ++j) if (x[i][j] != 0.0) grad[j] += e * x[i][j];
        }
        const double n = static_cast<double>(ids.size());
        m.b -= rate * gb / n;
        for (size_t j = 0; j < m.w.size(); ++j)
            m.w[j] -= rate * (grad[j] / n + lambda * m.w[j]);
    }
    return m;
}

double rawLogit(const Model& m, const vector<double>& x) {
    double z = m.b;
    for (size_t j = 0; j < m.w.size(); ++j) if (x[j] != 0.0) z += m.w[j] * x[j];
    return z;
}

struct Calibrator { double a = 1.0, b = 0.0; };
Calibrator fitPlatt(const vector<double>& logits, const vector<int>& y, const vector<size_t>& ids) {
    Calibrator c;
    if (ids.empty()) return c;
    for (int epoch = 0; epoch < 1200; ++epoch) {
        double ga = 0, gb = 0;
        for (size_t i : ids) {
            const double e = sigmoid(c.a * logits[i] + c.b) - y[i];
            ga += e * logits[i]; gb += e;
        }
        const double n = static_cast<double>(ids.size());
        c.a -= 0.03 * (ga / n + 0.001 * (c.a - 1.0));
        c.b -= 0.03 * gb / n;
    }
    return c;
}

vector<vector<size_t>> stratifiedFolds(const vector<int>& y, const vector<size_t>& ids, int k, unsigned seed) {
    vector<size_t> pos, neg;
    for (size_t i : ids) (y[i] ? pos : neg).push_back(i);
    mt19937 rng(seed); shuffle(pos.begin(), pos.end(), rng); shuffle(neg.begin(), neg.end(), rng);
    vector<vector<size_t>> folds(static_cast<size_t>(k));
    for (size_t i = 0; i < pos.size(); ++i) folds[i % k].push_back(pos[i]);
    for (size_t i = 0; i < neg.size(); ++i) folds[i % k].push_back(neg[i]);
    return folds;
}

bool runSelfTests() {
    const auto quoted = parseCsvLine("alpha,\"b,c\",\"say \"\"hi\"\"\"");
    if (quoted.size() != 3 || quoted[1] != "b,c" || quoted[2] != "say \"hi\"") return false;
    double value = 0;
    if (number("", value) || number("   ", value) || !number("-500", value) || value != -500) return false;
    vector<string> bom = {string("\xEF\xBB\xBF") + "month", "x"};
    stripUtf8Bom(bom);
    if (bom[0] != "month") return false;
    if (aiErrorLabel("INCLUSION", "INCLUSION") != optional<int>(0) ||
        aiErrorLabel("EXCLUSION", "INCLUSION") != optional<int>(1) ||
        aiErrorLabel("", "INCLUSION").has_value()) return false;
    if (!(sigmoid(-1000.0) >= 0.0 && sigmoid(-1000.0) <= 1.0 &&
          sigmoid(0.0) == 0.5 && sigmoid(1000.0) >= 0.0 && sigmoid(1000.0) <= 1.0)) return false;
    vector<vector<double>> x = {{-2.0},{-1.0},{1.0},{2.0}};
    vector<int> y = {0,0,1,1}; vector<size_t> ids = {0,1,2,3};
    Model m = trainLogistic(x,y,ids);
    if (!(m.w.size()==1 && m.w[0]>0 && sigmoid(rawLogit(m,x[3]))>sigmoid(rawLogit(m,x[0])))) return false;
    vector<double> logits(4); for(size_t i=0;i<4;++i) logits[i]=rawLogit(m,x[i]);
    Calibrator cal=fitPlatt(logits,y,ids);
    if (!(sigmoid(cal.a*logits[0]+cal.b)>=0 && sigmoid(cal.a*logits[0]+cal.b)<=1)) return false;
    auto folds=stratifiedFolds(y,ids,2,123);
    if(folds.size()!=2 || folds[0].empty() || folds[1].empty()) return false;
    vector<string> headers=kFeatureColumns;
    headers.push_back("FinalScore"); headers.push_back("EligibilityTarget");
    unordered_map<string,size_t> col;
    for(size_t i=0;i<headers.size();++i) col[headers[i]]=i;
    vector<Row> sample(2);
    for(auto& r:sample) r.cells.assign(headers.size(), "");
    sample[0].cells[col["NumIntegrantes"]]="1";
    sample[0].cells[col["HablaEspanol"]]="yes";
    sample[0].cells[col["EligibilityTarget"]]="INCLUSION";
    sample[1].cells[col["NumIntegrantes"]]="2";
    sample[1].cells[col["HablaEspanol"]]="unknown-category";
    sample[1].cells[col["ScoreCOMAR_PIL"]]="-500";
    sample[1].cells[col["ScoreIntenciones"]]="500";
    sample[1].cells[col["ScoreDuplicidad"]]="0";
    sample[1].cells[col["EligibilityTarget"]]="EXCLUSION";
    Encoder encoder(sample,col);
    if(find(encoder.names.begin(),encoder.names.end(),"ScoreCOMAR_PIL=FLAG_-500")==encoder.names.end() ||
       find(encoder.names.begin(),encoder.names.end(),"ScoreIntenciones=FLAG_+500")==encoder.names.end() ||
       find(encoder.names.begin(),encoder.names.end(),"ScoreDuplicidad=MISSING_NOT_APPLICABLE")==encoder.names.end() ||
       !encoder.cats[col["HablaEspanol"]].count("UNKNOWN")) return false;
    auto missingFeature=find(encoder.names.begin(),encoder.names.end(),"FemaleHeadedHousehold=MISSING_NOT_APPLICABLE");
    if(missingFeature==encoder.names.end() || encoder.x[0][static_cast<size_t>(missingFeature-encoder.names.begin())]!=1.0) return false;
    const string escaped=csvEscape("quoted, value");
    if(escaped!="\"quoted, value\"") return false;
    ofstream temp(".uncertainty_selftest.csv");
    temp<<"value\n"<<escaped<<'\n'; temp.close();
    ifstream check(".uncertainty_selftest.csv"); string header,row;
    bool outputOk=static_cast<bool>(getline(check,header)) && static_cast<bool>(getline(check,row)) && row==escaped;
    check.close(); std::remove(".uncertainty_selftest.csv");
    return outputOk;
}

vector<double> innerCrossfitLogits(const vector<vector<double>>& x, const vector<int>& y,
                                   const vector<size_t>& trainIds, int k) {
    vector<double> logits(y.size(), 0.0);
    const auto folds = stratifiedFolds(y, trainIds, k, 9173);
    for (int f = 0; f < k; ++f) {
        vector<bool> held(y.size(), false);
        for (size_t i : folds[f]) held[i] = true;
        vector<size_t> tr;
        for (size_t i : trainIds) if (!held[i]) tr.push_back(i);
        const Model m = trainLogistic(x, y, tr);
        for (size_t i : folds[f]) logits[i] = rawLogit(m, x[i]);
    }
    return logits;
}

struct Metrics { double auc=0, pr=0, brier=0, logloss=0, ece=0; size_t tp=0, tn=0, fp=0, fn=0; };
Metrics evaluate(const vector<int>& y, const vector<double>& p) {
    Metrics m; size_t n = y.size();
    vector<pair<double,int>> ranked; ranked.reserve(n);
    for (size_t i=0; i<n; ++i) {
        const double q = min(1.0-1e-15, max(1e-15, p[i]));
        m.brier += (q-y[i])*(q-y[i]);
        m.logloss += -(y[i]*log(q)+(1-y[i])*log(1-q));
        if (q >= 0.5) { if(y[i]) ++m.tp; else ++m.fp; }
        else { if(y[i]) ++m.fn; else ++m.tn; }
        ranked.emplace_back(q,y[i]);
    }
    if (!n) return m;
    m.brier/=n; m.logloss/=n;
    sort(ranked.begin(), ranked.end(), [](auto a, auto b){ return a.first < b.first; });
    size_t positives=0; for(int v:y) positives+=v;
    if (positives && positives<n) {
        long double rankSum=0; size_t rank=1;
        for(size_t i=0;i<n;) { size_t j=i+1; while(j<n && ranked[j].first==ranked[i].first) ++j;
            const double avg=(rank+(rank+(j-i)-1))/2.0;
            for(size_t q=i;q<j;++q) if(ranked[q].second) rankSum+=avg;
            rank += j-i; i=j;
        }
        m.auc=static_cast<double>((rankSum-positives*(positives+1)/2.0)/(positives*(n-positives)));
        double tp=0, fp=0, lastRecall=0, area=0;
        for (auto it=ranked.rbegin(); it!=ranked.rend(); ++it) {
            if(it->second) ++tp; else ++fp;
            const double recall=tp/positives;
            area += (recall-lastRecall)*(tp/(tp+fp)); lastRecall=recall;
        }
        m.pr=area;
    }
    const size_t bins=10;
    for(size_t b=0;b<bins;++b) {
        double ps=0, ys=0; size_t count=0;
        for(size_t i=0;i<n;++i) if((p[i]*bins>=b) && (b==bins-1 || p[i]*bins<(b+1))) { ps+=p[i]; ys+=y[i]; ++count; }
        if(count) m.ece += static_cast<double>(count)/n*abs(ps/count-ys/count);
    }
    return m;
}

pair<bool,bool> auditFlags(const Row& r, const unordered_map<string,size_t>& col) {
    auto get = [&](const string& name, double& v) { auto it=col.find(name); return it!=col.end() && number(r.cells[it->second],v); };
    double a=0,b=0,c=0,fs=0; bool ha=get("ScoreCOMAR_PIL",a), hb=get("ScoreIntenciones",b), hc=get("ScoreDuplicidad",c), hf=get("FinalScore",fs);
    const bool minus=(ha&&a==-500)||(hb&&b==-500)||(hc&&c==-500);
    const bool inclusion=r.target=="INCLUSION", exclusion=r.target=="EXCLUSION";
    const bool anomaly=(hf && minus && fs<30 && inclusion)||(ha && a==500 && hf && fs>30 && exclusion);
    const bool conflict=hf && minus && fs>30 && inclusion;
    return {anomaly, conflict};
}

string boolText(bool b) { return b ? "1" : "0"; }
}

int main(int argc, char** argv) {
    try {
        if (argc > 1 && string(argv[1]) == "--self-test") {
            if (!runSelfTests()) { cerr << "Self-tests failed.\n"; return 1; }
            cout << "All built-in self-tests passed.\n";
            return 0;
        }
        const string input = argc > 1 ? argv[1] : "S8.synthetic_cashy_sample.csv";
        ifstream in(input);
        if (!in) { cerr << "Cannot open CSV: " << input << '\n'; return 1; }
        string line;
        if (!getline(in,line)) { cerr << "CSV is empty.\n"; return 1; }
        auto headers=parseCsvLine(line);
        stripUtf8Bom(headers);
        unordered_map<string,size_t> col;
        for(size_t i=0;i<headers.size();++i) col[trim(headers[i])]=i;
        for(const string& need: {string("EligibilityTarget"),string("FinalScore"),string("ScoreCOMAR_PIL"),string("ScoreIntenciones"),string("ScoreDuplicidad"),string("month")}) if(!col.count(need)) throw runtime_error("Missing required column: "+need);
        const bool realMode=col.count("AIRecommendation")!=0;
        vector<Row> rows;
        size_t physicalLine=1, skipped=0;
        while(getline(in,line)) {
            ++physicalLine; if(trim(line).empty()) continue;
            Row r; r.originalRowId=physicalLine-1; r.cells=parseCsvLine(line);
            if(r.cells.size()!=headers.size()) { cerr<<"Skipping malformed CSV line "<<physicalLine<<" (field count mismatch).\n"; ++skipped; continue; }
            r.target=trim(r.cells[col.at("EligibilityTarget")]);
            if(r.target!="INCLUSION" && r.target!="EXCLUSION") { cerr<<"Skipping line "<<physicalLine<<" with unknown reference target.\n"; ++skipped; continue; }
            r.month=r.cells[col.at("month")];
            if(realMode) {
                r.aiRecommendation=trim(r.cells[col.at("AIRecommendation")]);
                auto label=aiErrorLabel(r.aiRecommendation,r.target);
                if(!label) throw runtime_error("AIRecommendation column exists but contains a blank or invalid class at CSV line "+to_string(physicalLine));
                r.aiErrorLabel=*label;
                r.y=*label;
            } else r.y=(r.target=="INCLUSION");
            auto flags=auditFlags(r,col); r.anomaly=flags.first; r.conflict=flags.second;
            rows.push_back(std::move(r));
        }
        if(rows.size()<10) throw runtime_error("At least 10 valid labeled rows are needed.");
        Encoder encoder(rows,col);
        vector<int> y; y.reserve(rows.size()); for(const auto& r:rows) y.push_back(r.y);
        size_t positives=count(y.begin(),y.end(),1), negatives=y.size()-positives;
        if(positives<2 || negatives<2) throw runtime_error("Need at least two rows in each reference class for cross-validation.");
        const int k=static_cast<int>(min<size_t>(5,min(positives,negatives)));
        vector<size_t> all(rows.size()); iota(all.begin(),all.end(),0);
        auto folds=stratifiedFolds(y,all,k,20261001);
        vector<double> oof(rows.size(),0.5);
        vector<double> oofLogits(rows.size(),0.0);
        vector<int> foldByRow(rows.size(),0);
        vector<Model> foldModels(static_cast<size_t>(k));
        vector<Calibrator> foldCals(static_cast<size_t>(k));
        for(int f=0;f<k;++f) {
            vector<bool> held(rows.size(),false); for(size_t i:folds[f]) held[i]=true;
            vector<size_t> tr; for(size_t i:all) if(!held[i]) tr.push_back(i);
            auto inner=innerCrossfitLogits(encoder.x,y,tr,min(4,static_cast<int>(min(count_if(tr.begin(),tr.end(),[&](size_t i){return y[i]==1;}),count_if(tr.begin(),tr.end(),[&](size_t i){return y[i]==0;})))));
            foldCals[f]=fitPlatt(inner,y,tr);
            foldModels[f]=trainLogistic(encoder.x,y,tr);
            for(size_t i:folds[f]) { foldByRow[i]=f; oofLogits[i]=rawLogit(foldModels[f],encoder.x[i]); oof[i]=sigmoid(foldCals[f].a*oofLogits[i]+foldCals[f].b); }
        }
        Metrics met=evaluate(y,oof);
        vector<double> innerFull=innerCrossfitLogits(encoder.x,y,all,min(5,static_cast<int>(min(positives,negatives))));
        Calibrator finalCal=fitPlatt(innerFull,y,all);
        Model finalModel=trainLogistic(encoder.x,y,all);

        ofstream out("uncertainty_results.csv");
        if(!out) throw runtime_error("Cannot create uncertainty_results.csv");
        out<<"row_id,month,AIRecommendation,EligibilityTarget,AIErrorLabel,proxy_predicted_reference_class,proxy_probability_of_reference_inclusion,proxy_uncertainty,predicted_AIErrorProbability,uncertainty,anomaly_flag,conflict_flag\n"<<fixed<<setprecision(6);
        for(size_t i=0;i<rows.size();++i) {
            const string month=rows[i].month;
            const double proxyUncertainty=min(oof[i],1.0-oof[i]);
            out<<rows[i].originalRowId<<','<<csvEscape(month)<<','<<csvEscape(rows[i].aiRecommendation)<<','<<rows[i].target<<',';
            if(realMode) out<<rows[i].aiErrorLabel;
            out<<',';
            if(!realMode) out<<(oof[i]>=0.5?"INCLUSION":"EXCLUSION");
            out<<',';
            if(!realMode) out<<oof[i];
            out<<',';
            if(!realMode) out<<proxyUncertainty;
            out<<',';
            if(realMode) out<<oof[i];
            out<<','<<(realMode?oof[i]:proxyUncertainty)<<','
               <<boolText(rows[i].anomaly)<<','<<boolText(rows[i].conflict)<<'\n';
        }

        ofstream weights("feature_weights.csv");
        weights<<"feature,weight\n"<<fixed<<setprecision(8);
        vector<pair<double,string>> sortedWeights;
        for(size_t j=0;j<finalModel.w.size();++j) {
            const double w=finalCal.a*finalModel.w[j];
            weights<<csvEscape(encoder.names[j])<<','<<w<<'\n';
            sortedWeights.emplace_back(w,encoder.names[j]);
        }
        weights<<"calibrated_intercept,"<<(finalCal.a*finalModel.b+finalCal.b)<<'\n';
        sort(sortedWeights.begin(),sortedWeights.end(),[](const auto&a,const auto&b){return abs(a.first)>abs(b.first);});

        ofstream preprocessing("model_preprocessing.csv");
        preprocessing<<"input_column,encoding,mean,scale,levels\n"<<fixed<<setprecision(8);
        for(size_t h=0;h<kFeatureColumns.size();++h) {
            const string& name=kFeatureColumns[h];
            if(find(kNumericColumns.begin(),kNumericColumns.end(),name)!=kNumericColumns.end()) {
                preprocessing<<csvEscape(name)<<",standardized_numeric_with_missing_indicator,"<<encoder.means[h]<<','<<encoder.scales[h]<<",\n";
            } else {
                vector<pair<size_t,string>> levels;
                for(const auto& item:encoder.cats[h]) levels.emplace_back(item.second,item.first);
                sort(levels.begin(),levels.end());
                string joined;
                for(const auto& item:levels) { if(!joined.empty()) joined+='|'; joined+=item.second; }
                preprocessing<<csvEscape(name)<<",one_hot_categorical,,,"<<csvEscape(joined)<<'\n';
            }
        }

        ofstream report("uncertainty_report.txt");
        report<<(realMode?"REAL AI ERROR MODE: an independent AIRecommendation column was supplied.\n":"PROXY MODE: no independent AIRecommendation exists in the repository or supplied CSV.\n")
              <<(realMode?"The model predicts whether the AI recommendation disagrees with the recorded EligibilityTarget.\n":"The probabilities predict the institution's recorded EligibilityTarget (INCLUSION), not AI error or human override.\n")
              <<(realMode?"uncertainty is the calibrated probability of AIErrorLabel=1.\n":"The proxy classifier predicts INCLUSION when P(INCLUSION)>=0.5, otherwise EXCLUSION. proxy_uncertainty=min(P(INCLUSION),1-P(INCLUSION)) estimates the probability that this proxy class differs from the recorded reference. It is not an AI-error probability.\n")
              <<"EligibilityTarget is a recorded reference determination, not objective truth about household need.\n"
              <<"The supplied synthetic sample is not evidence of real-world model performance.\n\n"
              <<"Rows="<<rows.size()<<"; skipped="<<skipped<<"; positive model labels="<<positives<<"; negative model labels="<<negatives<<"; positive rate="<<double(positives)/rows.size()<<"\n"
              <<(realMode?"AI-correct="+to_string(negatives)+"; AI-wrong="+to_string(positives)+".\n":"AI-correct/AI-wrong counts: unavailable (no independent AIRecommendation).\n")
              <<"Stratified outer folds="<<k<<"; threshold=0.5\n"
              <<(realMode?"Confusion matrix (AI-error positive): TP=":"Confusion matrix (reference inclusion positive): TP=")<<met.tp<<" FP="<<met.fp<<" TN="<<met.tn<<" FN="<<met.fn<<"\n"
              <<"ROC_AUC="<<met.auc<<" PR_AUC="<<met.pr<<" LogLoss="<<met.logloss<<" Brier="<<met.brier<<" ECE10="<<met.ece<<"\n"
              <<"Calibration is Platt logistic calibration fit from inner out-of-fold training predictions. Metrics are outer-fold predictions.\n\n"
              <<(realMode?"Largest absolute calibrated model weights (positive raises AI-error log odds):\n":"Largest absolute calibrated model weights (positive raises recorded-INCLUSION log odds):\n");
        for(size_t j=0;j<min<size_t>(20,sortedWeights.size());++j) report<<sortedWeights[j].second<<" : "<<sortedWeights[j].first<<'\n';
        report<<(realMode?"\nHighest AI-error uncertainty cases (row_id, recommendation, reference, error label, probability, anomaly, conflict):\n":"\nHighest proxy_uncertainty cases (row_id, month, probability of recorded INCLUSION, proxy_uncertainty, anomaly, conflict):\n");
        vector<size_t> order(rows.size()); iota(order.begin(),order.end(),0);
        sort(order.begin(),order.end(),[&](size_t a,size_t b){return (realMode?oof[a]:min(oof[a],1-oof[a]))>(realMode?oof[b]:min(oof[b],1-oof[b]));});
        for(size_t n=0;n<min<size_t>(20,order.size());++n) {
            const size_t i=order[n]; const size_t f=static_cast<size_t>(foldByRow[i]);
            vector<pair<double,string>> terms;
            for(size_t j=0;j<encoder.names.size();++j) {
                const double term=foldCals[f].a*foldModels[f].w[j]*encoder.x[i][j];
                if(term!=0.0) terms.emplace_back(term,encoder.names[j]);
            }
            sort(terms.begin(),terms.end(),[](const auto&a,const auto&b){return a.first>b.first;});
            report<<"\nrow_id="<<rows[i].originalRowId<<", month="<<rows[i].month
                  <<(realMode?", AIRecommendation="+rows[i].aiRecommendation+", EligibilityTarget="+rows[i].target+", AIErrorLabel="+to_string(rows[i].aiErrorLabel)+", AI-error probability=":", P(reference INCLUSION)=")<<oof[i]
                  <<(realMode?", uncertainty=":", proxy_uncertainty=")<<(realMode?oof[i]:min(oof[i],1-oof[i]))<<", anomaly="<<boolText(rows[i].anomaly)
                  <<", conflict="<<boolText(rows[i].conflict)<<(realMode?"\n  strongest positive AI-error log-odds contributions:":"\n  strongest positive inclusion-log-odds contributions:");
            size_t shown=0;
            for(const auto& term:terms) if(term.first>0 && shown++<3) report<<" "<<term.second<<"("<<term.first<<")";
            if(shown==0) report<<" none";
            report<<(realMode?"\n  strongest negative AI-error log-odds contributions:":"\n  strongest negative inclusion-log-odds contributions:");
            shown=0;
            for(auto it=terms.rbegin();it!=terms.rend();++it) if(it->first<0 && shown++<3) report<<" "<<it->second<<"("<<it->first<<")";
            if(shown==0) report<<" none";
            report<<'\n';
        }

        cout<<"Mode: "<<(realMode?"REAL AI ERROR":"PROXY")<<"\nRows: "<<rows.size()<<" (skipped "<<skipped<<")\n"
            <<(realMode?"AI wrong: ":"Reference INCLUSION: ")<<positives<<"; "<<(realMode?"AI correct: ":"EXCLUSION: ")<<negatives<<"\n"
            <<"Stratified CV folds: "<<k<<"\nROC AUC: "<<met.auc<<"\nPR AUC: "<<met.pr<<"\nLog loss: "<<met.logloss<<"\nBrier: "<<met.brier<<"\nECE10: "<<met.ece<<"\n"
            <<"Wrote uncertainty_results.csv, feature_weights.csv, model_preprocessing.csv, uncertainty_report.txt\n";
        return 0;
    } catch(const exception& e) { cerr<<"Error: "<<e.what()<<'\n'; return 1; }
}

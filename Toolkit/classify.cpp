#include <iostream>
#include <algorithm>
#include <fstream>
#include <random>
#include <sstream>
#include <string>
#include <vector>
#include <unordered_map>
#include <utility>

using namespace std;

struct Record {
    vector<string> fields; // The complete original CSV row
    double scoreComarPil = 0.0;
    double scoreIntenciones = 0.0;
    double scoreDuplicidad = 0.0;
    double finalScore = 0.0;
    string eligibilityTarget;
    string aiPrediction;
    string aiUncertainty;
    string sourceGroup; // Internal label used to assign the blind-test behavior
};

string trim(const string& text) {
    const string whitespace = " \t\r\n";
    size_t first = text.find_first_not_of(whitespace);

    if (first == string::npos) {
        return "";
    }

    size_t last = text.find_last_not_of(whitespace);
    return text.substr(first, last - first + 1);
}

// Parses one CSV line, including quoted fields and escaped quotes ("").
vector<string> parseCsvLine(const string& line) {
    vector<string> fields;
    string field;
    bool insideQuotes = false;

    for (size_t i = 0; i < line.size(); ++i) {
        char ch = line[i];

        if (ch == '"') {
            if (insideQuotes && i + 1 < line.size() && line[i + 1] == '"') {
                field += '"';
                ++i;
            } else {
                insideQuotes = !insideQuotes;
            }
        } else if (ch == ',' && !insideQuotes) {
            fields.push_back(field);
            field.clear();
        } else {
            field += ch;
        }
    }

    fields.push_back(field);
    return fields;
}

// Returns true if the whole cell contains a valid number.
// Blank cells and invalid numbers return false.
bool parseNumber(const string& text, double& value) {
    string cleaned = trim(text);
    if (cleaned.empty()) {
        return false;
    }

    try {
        size_t charactersUsed = 0;
        value = stod(cleaned, &charactersUsed);
        return charactersUsed == cleaned.size();
    } catch (...) {
        return false;
    }
}

string csvEscape(const string& value) {
    if (value.find_first_of(",\"\r\n") == string::npos) {
        return value;
    }

    string escaped = "\"";
    for (char ch : value) {
        if (ch == '"') {
            escaped += '"';
        }
        escaped += ch;
    }
    escaped += '"';
    return escaped;
}

void addRandomSample(const vector<Record>& source,
                     size_t requestedCount,
                     const string& sourceGroup,
                     vector<Record>& testSet,
                     mt19937& randomEngine) {
    vector<size_t> indices(source.size());
    for (size_t i = 0; i < indices.size(); ++i) {
        indices[i] = i;
    }
    shuffle(indices.begin(), indices.end(), randomEngine);

    const size_t sampleCount = min(requestedCount, source.size());
    for (size_t i = 0; i < sampleCount; ++i) {
        Record record = source[indices[i]];
        record.sourceGroup = sourceGroup;
        testSet.push_back(std::move(record));
    }
}

int main() {
    const string inputFile = "S8.synthetic_cashy_sample.csv";

    ifstream file(inputFile);
    if (!file.is_open()) {
        cerr << "Error: could not open input file:\n"
             << inputFile << '\n';
        return 1;
    }

    string line;
    if (!getline(file, line)) {
        cerr << "Error: the CSV file is empty.\n";
        return 1;
    }

    vector<string> headers = parseCsvLine(line);

    // Remove a UTF-8 byte-order mark if the file has one.
    if (!headers.empty() && headers[0].size() >= 3 &&
        static_cast<unsigned char>(headers[0][0]) == 0xEF &&
        static_cast<unsigned char>(headers[0][1]) == 0xBB &&
        static_cast<unsigned char>(headers[0][2]) == 0xBF) {
        headers[0].erase(0, 3);
    }

    unordered_map<string, size_t> columnIndex;
    for (size_t i = 0; i < headers.size(); ++i) {
        columnIndex[trim(headers[i])] = i;
    }

    const vector<string> requiredColumns = {
        "ScoreCOMAR_PIL",
        "ScoreIntenciones",
        "ScoreDuplicidad",
        "FinalScore",
        "EligibilityTarget"
    };

    for (const string& name : requiredColumns) {
        if (columnIndex.find(name) == columnIndex.end()) {
            cerr << "Error: required column not found: " << name << '\n';
            return 1;
        }
    }

    vector<Record> anomalies;
    vector<Record> conflicts;
    vector<Record> rest;

    size_t rowsRead = 0;
    size_t rowsSkipped = 0;
    size_t lineNumber = 1;

    while (getline(file, line)) {
        ++lineNumber;

        if (trim(line).empty()) {
            continue;
        }

        ++rowsRead;

        Record record;
        record.fields = parseCsvLine(line);

        if (record.fields.size() != headers.size()) {
            cerr << "Warning: skipping line " << lineNumber
                 << " because it has " << record.fields.size()
                 << " fields; expected " << headers.size() << ".\n";
            ++rowsSkipped;
            continue;
        }

        // A blank score means "not available", not that the entire record
        // should be discarded. It cannot match either -500 or 500.
        double scoreComarPil = 0.0;
        double scoreIntenciones = 0.0;
        double scoreDuplicidad = 0.0;
        double finalScore = 0.0;

        bool hasComarPil = parseNumber(
            record.fields[columnIndex["ScoreCOMAR_PIL"]], scoreComarPil);
        bool hasIntenciones = parseNumber(
            record.fields[columnIndex["ScoreIntenciones"]], scoreIntenciones);
        bool hasDuplicidad = parseNumber(
            record.fields[columnIndex["ScoreDuplicidad"]], scoreDuplicidad);
        bool hasFinalScore = parseNumber(
            record.fields[columnIndex["FinalScore"]], finalScore);

        if (!hasFinalScore) {
            cerr << "Warning: skipping line " << lineNumber
                 << " because FinalScore is blank or invalid.\n";
            ++rowsSkipped;
            continue;
        }

        record.scoreComarPil = scoreComarPil;
        record.scoreIntenciones = scoreIntenciones;
        record.scoreDuplicidad = scoreDuplicidad;
        record.finalScore = finalScore;
        record.eligibilityTarget =
            trim(record.fields[columnIndex["EligibilityTarget"]]);

        bool hasMinus500 =
            (hasComarPil && record.scoreComarPil == -500) ||
            (hasIntenciones && record.scoreIntenciones == -500) ||
            (hasDuplicidad && record.scoreDuplicidad == -500);

        bool isInclusion = record.eligibilityTarget == "INCLUSION";
        bool isExclusion = record.eligibilityTarget == "EXCLUSION";

        bool isAnomaly =
            (hasMinus500 && record.finalScore < 30 && isInclusion) ||
            (hasComarPil && record.scoreComarPil == 500 &&
             record.finalScore > 30 && isExclusion);

        bool isConflict =
            hasMinus500 && record.finalScore > 30 && isInclusion;

        if (isAnomaly) {
            anomalies.push_back(std::move(record));
        } else if (isConflict) {
            conflicts.push_back(std::move(record));
        } else {
            rest.push_back(std::move(record));
        }
    }

    cout << "Rows read: " << rowsRead << '\n';
    cout << "Rows skipped: " << rowsSkipped << '\n';
    cout << "Anomalies: " << anomalies.size() << '\n';
    cout << "Conflicts: " << conflicts.size() << '\n';
    cout << "Rest: " << rest.size() << '\n';

    // Build the requested stratified test mix, taking all available records
    // from a group if that group is smaller than its requested sample size.
    random_device seed;
    mt19937 randomEngine(seed());
    vector<Record> testSet;
    testSet.reserve(100);
    addRandomSample(anomalies, 20, "anomaly", testSet, randomEngine);
    addRandomSample(conflicts, 30, "conflict", testSet, randomEngine);
    addRandomSample(rest, 50, "rest", testSet, randomEngine);

    // Wizard-of-Oz predictions: deliberately wrong and overconfident for
    // anomaly/conflict cases, correct with modest uncertainty for rest cases.
    for (Record& record : testSet) {
        if (record.sourceGroup == "anomaly" || record.sourceGroup == "conflict") {
            if (record.eligibilityTarget == "INCLUSION") {
                record.aiPrediction = "EXCLUSION";
            } else if (record.eligibilityTarget == "EXCLUSION") {
                record.aiPrediction = "INCLUSION";
            } else {
                cerr << "Error: unsupported EligibilityTarget value in sampled record: "
                     << record.eligibilityTarget << '\n';
                return 1;
            }
            record.aiUncertainty = "0.0";
        } else {
            record.aiPrediction = record.eligibilityTarget;
            record.aiUncertainty = "0.15";
        }
    }

    // Randomize the mixed sample so its source strata are not visible by order.
    shuffle(testSet.begin(), testSet.end(), randomEngine);

    const string outputFile = "audit_blind_test.csv";
    ofstream output(outputFile);
    if (!output.is_open()) {
        cerr << "Error: could not create output file:\n" << outputFile << '\n';
        return 1;
    }

    // Write all original columns except the two historical-answer columns.
    bool firstColumn = true;
    for (size_t i = 0; i < headers.size(); ++i) {
        const string header = trim(headers[i]);
        if (header == "EligibilityTarget" || header == "Elegibilidad") {
            continue;
        }
        if (!firstColumn) output << ',';
        output << csvEscape(headers[i]);
        firstColumn = false;
    }
    output << ",aiPrediction,aiUncertainty\n";

    for (const Record& record : testSet) {
        firstColumn = true;
        for (size_t i = 0; i < record.fields.size(); ++i) {
            const string header = trim(headers[i]);
            if (header == "EligibilityTarget" || header == "Elegibilidad") {
                continue;
            }
            if (!firstColumn) output << ',';
            output << csvEscape(record.fields[i]);
            firstColumn = false;
        }
        output << ',' << csvEscape(record.aiPrediction)
               << ',' << csvEscape(record.aiUncertainty) << '\n';
    }

    if (!output) {
        cerr << "Error: failed while writing " << outputFile << '\n';
        return 1;
    }

    cout << "Blind test rows written: " << testSet.size() << '\n';
    cout << "Blind test CSV: " << outputFile << '\n';

    return 0;
}

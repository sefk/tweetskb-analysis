#!/usr/bin/env bash
# Downloads all TweetsKB monthly files from Zenodo and GESIS.
# Source: https://data.gesis.org/tweetskb/
# Files are gzip-compressed N3 RDF, ~3-5 GB each (~600+ GB total).
# Uses wget -c so interrupted downloads can be resumed.

set -euo pipefail

OUTDIR="${1:-tweetskb_data}"
mkdir -p "$OUTDIR"
cd "$OUTDIR"

download() {
    local url="$1"
    local filename="$2"
    if [[ -f "$filename" ]]; then
        echo "Already exists, skipping: $filename"
        return
    fi
    echo "Downloading: $filename"
    wget -c -O "$filename" "$url"
}

# Part 1 — Jan 2013 – Feb 2014 (zenodo.org/record/573852)
download "https://zenodo.org/records/573852/files/month_2013-01.n3.gz?download=1" "month_2013-01.n3.gz"
download "https://zenodo.org/records/573852/files/month_2013-02.n3.gz?download=1" "month_2013-02.n3.gz"
download "https://zenodo.org/records/573852/files/month_2013-03.n3.gz?download=1" "month_2013-03.n3.gz"
download "https://zenodo.org/records/573852/files/month_2013-04.n3.gz?download=1" "month_2013-04.n3.gz"
download "https://zenodo.org/records/573852/files/month_2013-05.n3.gz?download=1" "month_2013-05.n3.gz"
download "https://zenodo.org/records/573852/files/month_2013-06.n3.gz?download=1" "month_2013-06.n3.gz"
download "https://zenodo.org/records/573852/files/month_2013-07.n3.gz?download=1" "month_2013-07.n3.gz"
download "https://zenodo.org/records/573852/files/month_2013-08.n3.gz?download=1" "month_2013-08.n3.gz"
download "https://zenodo.org/records/573852/files/month_2013-09.n3.gz?download=1" "month_2013-09.n3.gz"
download "https://zenodo.org/records/573852/files/month_2013-10.n3.gz?download=1" "month_2013-10.n3.gz"
download "https://zenodo.org/records/573852/files/month_2013-11.n3.gz?download=1" "month_2013-11.n3.gz"
download "https://zenodo.org/records/573852/files/month_2013-12.n3.gz?download=1" "month_2013-12.n3.gz"
download "https://zenodo.org/records/573852/files/month_2014-01.n3.gz?download=1" "month_2014-01.n3.gz"
download "https://zenodo.org/records/573852/files/month_2014-02.n3.gz?download=1" "month_2014-02.n3.gz"

# Part 2 — Mar 2014 – Dec 2014 (zenodo.org/record/577572)
download "https://zenodo.org/records/577572/files/month_2014-03.n3.gz?download=1" "month_2014-03.n3.gz"
download "https://zenodo.org/records/577572/files/month_2014-04.n3.gz?download=1" "month_2014-04.n3.gz"
download "https://zenodo.org/records/577572/files/month_2014-05.n3.gz?download=1" "month_2014-05.n3.gz"
download "https://zenodo.org/records/577572/files/month_2014-06.n3.gz?download=1" "month_2014-06.n3.gz"
download "https://zenodo.org/records/577572/files/month_2014-07.n3.gz?download=1" "month_2014-07.n3.gz"
download "https://zenodo.org/records/577572/files/month_2014-08.n3.gz?download=1" "month_2014-08.n3.gz"
download "https://zenodo.org/records/577572/files/month_2014-09.n3.gz?download=1" "month_2014-09.n3.gz"
download "https://zenodo.org/records/577572/files/month_2014-10.n3.gz?download=1" "month_2014-10.n3.gz"
download "https://zenodo.org/records/577572/files/month_2014-11.n3.gz?download=1" "month_2014-11.n3.gz"
download "https://zenodo.org/records/577572/files/month_2014-12.n3.gz?download=1" "month_2014-12.n3.gz"

# Part 3 — Jan 2015 – Oct 2015 (zenodo.org/record/579597)
download "https://zenodo.org/records/579597/files/month_2015-01.n3.gz?download=1" "month_2015-01.n3.gz"
download "https://zenodo.org/records/579597/files/month_2015-02.n3.gz?download=1" "month_2015-02.n3.gz"
download "https://zenodo.org/records/579597/files/month_2015-03.n3.gz?download=1" "month_2015-03.n3.gz"
download "https://zenodo.org/records/579597/files/month_2015-04.n3.gz?download=1" "month_2015-04.n3.gz"
download "https://zenodo.org/records/579597/files/month_2015-05.n3.gz?download=1" "month_2015-05.n3.gz"
download "https://zenodo.org/records/579597/files/month_2015-06.n3.gz?download=1" "month_2015-06.n3.gz"
download "https://zenodo.org/records/579597/files/month_2015-07.n3.gz?download=1" "month_2015-07.n3.gz"
download "https://zenodo.org/records/579597/files/month_2015-08.n3.gz?download=1" "month_2015-08.n3.gz"
download "https://zenodo.org/records/579597/files/month_2015-09.n3.gz?download=1" "month_2015-09.n3.gz"
download "https://zenodo.org/records/579597/files/month_2015-10.n3.gz?download=1" "month_2015-10.n3.gz"

# Part 4 — Nov 2015 – Aug 2016 (zenodo.org/record/579601)
download "https://zenodo.org/records/579601/files/month_2015-11.n3.gz?download=1" "month_2015-11.n3.gz"
download "https://zenodo.org/records/579601/files/month_2015-12.n3.gz?download=1" "month_2015-12.n3.gz"
download "https://zenodo.org/records/579601/files/month_2016-01.n3.gz?download=1" "month_2016-01.n3.gz"
download "https://zenodo.org/records/579601/files/month_2016-02.n3.gz?download=1" "month_2016-02.n3.gz"
download "https://zenodo.org/records/579601/files/month_2016-03.n3.gz?download=1" "month_2016-03.n3.gz"
download "https://zenodo.org/records/579601/files/month_2016-04.n3.gz?download=1" "month_2016-04.n3.gz"
download "https://zenodo.org/records/579601/files/month_2016-05.n3.gz?download=1" "month_2016-05.n3.gz"
download "https://zenodo.org/records/579601/files/month_2016-06.n3.gz?download=1" "month_2016-06.n3.gz"
download "https://zenodo.org/records/579601/files/month_2016-07.n3.gz?download=1" "month_2016-07.n3.gz"
download "https://zenodo.org/records/579601/files/month_2016-08.n3.gz?download=1" "month_2016-08.n3.gz"

# Part 5 — Sep 2016 – Oct 2017 (zenodo.org/record/1095592)
# Note: Nov 2017 appears in both Part 5 and Part 6; using Part 6's copy below.
download "https://zenodo.org/records/1095592/files/month_2016-09.n3.gz?download=1" "month_2016-09.n3.gz"
download "https://zenodo.org/records/1095592/files/month_2016-10.n3.gz?download=1" "month_2016-10.n3.gz"
download "https://zenodo.org/records/1095592/files/month_2016-11.n3.gz?download=1" "month_2016-11.n3.gz"
download "https://zenodo.org/records/1095592/files/month_2016-12.n3.gz?download=1" "month_2016-12.n3.gz"
download "https://zenodo.org/records/1095592/files/month_2017-01.n3.gz?download=1" "month_2017-01.n3.gz"
download "https://zenodo.org/records/1095592/files/month_2017-02.n3.gz?download=1" "month_2017-02.n3.gz"
download "https://zenodo.org/records/1095592/files/month_2017-03.n3.gz?download=1" "month_2017-03.n3.gz"
download "https://zenodo.org/records/1095592/files/month_2017-04.n3.gz?download=1" "month_2017-04.n3.gz"
download "https://zenodo.org/records/1095592/files/month_2017-05.n3.gz?download=1" "month_2017-05.n3.gz"
download "https://zenodo.org/records/1095592/files/month_2017-06.n3.gz?download=1" "month_2017-06.n3.gz"
download "https://zenodo.org/records/1095592/files/month_2017-07.n3.gz?download=1" "month_2017-07.n3.gz"
download "https://zenodo.org/records/1095592/files/month_2017-08.n3.gz?download=1" "month_2017-08.n3.gz"
download "https://zenodo.org/records/1095592/files/month_2017-09.n3.gz?download=1" "month_2017-09.n3.gz"
download "https://zenodo.org/records/1095592/files/month_2017-10.n3.gz?download=1" "month_2017-10.n3.gz"

# Part 6 — Nov 2017 – Mar 2018 (zenodo.org/record/1808741)
download "https://zenodo.org/records/1808741/files/month_2017-11.n3.gz?download=1" "month_2017-11.n3.gz"
download "https://zenodo.org/records/1808741/files/month_2017-12.n3.gz?download=1" "month_2017-12.n3.gz"
download "https://zenodo.org/records/1808741/files/month_2018-01.n3.gz?download=1" "month_2018-01.n3.gz"
download "https://zenodo.org/records/1808741/files/month_2018-02.n3.gz?download=1" "month_2018-02.n3.gz"
download "https://zenodo.org/records/1808741/files/month_2018-03.n3.gz?download=1" "month_2018-03.n3.gz"

# Part 7 — Apr 2018 – Apr 2019 (zenodo.org/record/3828929)
download "https://zenodo.org/api/records/3828929/files/month_2018-04.n3.gz/content" "month_2018-04.n3.gz"
download "https://zenodo.org/api/records/3828929/files/month_2018-05.n3.gz/content" "month_2018-05.n3.gz"
download "https://zenodo.org/api/records/3828929/files/month_2018-06.n3.gz/content" "month_2018-06.n3.gz"
download "https://zenodo.org/api/records/3828929/files/month_2018-07.n3.gz/content" "month_2018-07.n3.gz"
download "https://zenodo.org/api/records/3828929/files/month_2018-08.n3.gz/content" "month_2018-08.n3.gz"
download "https://zenodo.org/api/records/3828929/files/month_2018-09.n3.gz/content" "month_2018-09.n3.gz"
download "https://zenodo.org/api/records/3828929/files/month_2018-10.n3.gz/content" "month_2018-10.n3.gz"
download "https://zenodo.org/api/records/3828929/files/month_2018-11.n3.gz/content" "month_2018-11.n3.gz"
download "https://zenodo.org/api/records/3828929/files/month_2018-12.n3.gz/content" "month_2018-12.n3.gz"
download "https://zenodo.org/api/records/3828929/files/month_2019-01.n3.gz/content" "month_2019-01.n3.gz"
download "https://zenodo.org/api/records/3828929/files/month_2019-02.n3.gz/content" "month_2019-02.n3.gz"
download "https://zenodo.org/api/records/3828929/files/month_2019-03.n3.gz/content" "month_2019-03.n3.gz"
download "https://zenodo.org/api/records/3828929/files/month_2019-04.n3.gz/content" "month_2019-04.n3.gz"

# Part 8 — May 2019 – Apr 2020 (zenodo.org/record/3828949)
download "https://zenodo.org/records/3828949/files/month_2019-05.n3.gz?download=1" "month_2019-05.n3.gz"
download "https://zenodo.org/records/3828949/files/month_2019-06.n3.gz?download=1" "month_2019-06.n3.gz"
download "https://zenodo.org/records/3828949/files/month_2019-07.n3.gz?download=1" "month_2019-07.n3.gz"
download "https://zenodo.org/records/3828949/files/month_2019-08.n3.gz?download=1" "month_2019-08.n3.gz"
download "https://zenodo.org/records/3828949/files/month_2019-09.n3.gz?download=1" "month_2019-09.n3.gz"
download "https://zenodo.org/records/3828949/files/month_2019-10.n3.gz?download=1" "month_2019-10.n3.gz"
download "https://zenodo.org/records/3828949/files/month_2019-11.n3.gz?download=1" "month_2019-11.n3.gz"
download "https://zenodo.org/records/3828949/files/month_2019-12.n3.gz?download=1" "month_2019-12.n3.gz"
download "https://zenodo.org/records/3828949/files/month_2020-01.n3.gz?download=1" "month_2020-01.n3.gz"
download "https://zenodo.org/records/3828949/files/month_2020-02.n3.gz?download=1" "month_2020-02.n3.gz"
download "https://zenodo.org/records/3828949/files/month_2020-03.n3.gz?download=1" "month_2020-03.n3.gz"
download "https://zenodo.org/records/3828949/files/month_2020-04.n3.gz?download=1" "month_2020-04.n3.gz"

# Part 9 — May 2020 – Dec 2020 (zenodo.org/record/4420178)
download "https://zenodo.org/records/4420178/files/month_2020-05.n3.gz?download=1" "month_2020-05.n3.gz"
download "https://zenodo.org/records/4420178/files/month_2020-06.n3.gz?download=1" "month_2020-06.n3.gz"
download "https://zenodo.org/records/4420178/files/month_2020-07.n3.gz?download=1" "month_2020-07.n3.gz"
download "https://zenodo.org/records/4420178/files/month_2020-08.n3.gz?download=1" "month_2020-08.n3.gz"
download "https://zenodo.org/records/4420178/files/month_2020-09.n3.gz?download=1" "month_2020-09.n3.gz"
download "https://zenodo.org/records/4420178/files/month_2020-10.n3.gz?download=1" "month_2020-10.n3.gz"
download "https://zenodo.org/records/4420178/files/month_2020-11.n3.gz?download=1" "month_2020-11.n3.gz"
download "https://zenodo.org/records/4420178/files/month_2020-12.n3.gz?download=1" "month_2020-12.n3.gz"

# Part 10 — Jan 2021 – Dec 2021 (doi.org/10.7802/2472 → access.gesis.org)
download "https://access.gesis.org/sharing/2472/3966" "month_2021-01.n3.gz"
download "https://access.gesis.org/sharing/2472/3967" "month_2021-02.n3.gz"
download "https://access.gesis.org/sharing/2472/3968" "month_2021-03.n3.gz"
download "https://access.gesis.org/sharing/2472/3969" "month_2021-04.n3.gz"
download "https://access.gesis.org/sharing/2472/3970" "month_2021-05.n3.gz"
download "https://access.gesis.org/sharing/2472/3971" "month_2021-06.n3.gz"
download "https://access.gesis.org/sharing/2472/3972" "month_2021-07.n3.gz"
download "https://access.gesis.org/sharing/2472/3973" "month_2021-08.n3.gz"
download "https://access.gesis.org/sharing/2472/3974" "month_2021-09.n3.gz"
download "https://access.gesis.org/sharing/2472/3975" "month_2021-10.n3.gz"
download "https://access.gesis.org/sharing/2472/3976" "month_2021-11.n3.gz"
download "https://access.gesis.org/sharing/2472/3977" "month_2021-12.n3.gz"

# Part 11 — Jan 2022 – Aug 2022 (doi.org/10.7802/2473 → access.gesis.org)
download "https://access.gesis.org/sharing/2473/3980" "month_2022-01.n3.gz"
download "https://access.gesis.org/sharing/2473/3981" "month_2022-02.n3.gz"
download "https://access.gesis.org/sharing/2473/3982" "month_2022-03.n3.gz"
download "https://access.gesis.org/sharing/2473/3983" "month_2022-04.n3.gz"
download "https://access.gesis.org/sharing/2473/3984" "month_2022-05.n3.gz"
download "https://access.gesis.org/sharing/2473/3985" "month_2022-06.n3.gz"
download "https://access.gesis.org/sharing/2473/3986" "month_2022-07.n3.gz"
download "https://access.gesis.org/sharing/2473/3987" "month_2022-08.n3.gz"

# Part 12 — Sep 2022 – Jun 2023 (doi.org/10.7802/2781 → access.gesis.org)
download "https://access.gesis.org/sharing/2781/6035" "month_2022-09.n3.gz"
download "https://access.gesis.org/sharing/2781/6036" "month_2022-10.n3.gz"
download "https://access.gesis.org/sharing/2781/6037" "month_2022-11.n3.gz"
download "https://access.gesis.org/sharing/2781/6038" "month_2022-12.n3.gz"
download "https://access.gesis.org/sharing/2781/6039" "month_2023-01.n3.gz"
download "https://access.gesis.org/sharing/2781/6040" "month_2023-02.n3.gz"
download "https://access.gesis.org/sharing/2781/6041" "month_2023-03.n3.gz"
download "https://access.gesis.org/sharing/2781/6042" "month_2023-04.n3.gz"
download "https://access.gesis.org/sharing/2781/6043" "month_2023-05.n3.gz"
download "https://access.gesis.org/sharing/2781/6044" "month_2023-06.n3.gz"

echo "All downloads complete. Files saved to: $(pwd)"

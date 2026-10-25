CREATE LIGHTNING DATABASE WHY_CHECKIN DESCRIBE BY "Health check-in agent, user habit log and public health sources" OPTIONS ();

CREATE LIGHTNING FILESTORE TABLE user_log FROM WHY_CHECKIN
FORMAT csv
OPTIONS (
  path "file:///home/zetaris/customer-data/shared/why_checkin/user_log",
  header "true",
  multiLine "true",
  escape "\"",
  quote "\""
);

CREATE LIGHTNING FILESTORE TABLE nutrient_limits FROM WHY_CHECKIN
FORMAT csv
OPTIONS (
  path "file:///home/zetaris/customer-data/shared/why_checkin/nutrient_limits",
  header "true",
  multiLine "true",
  escape "\"",
  quote "\""
);

CREATE LIGHTNING FILESTORE TABLE myhealthfinder FROM WHY_CHECKIN
FORMAT csv
OPTIONS (
  path "file:///home/zetaris/customer-data/shared/why_checkin/myhealthfinder",
  header "true",
  multiLine "true",
  escape "\"",
  quote "\""
);

CREATE LIGHTNING FILESTORE TABLE medlineplus FROM WHY_CHECKIN
FORMAT csv
OPTIONS (
  path "file:///home/zetaris/customer-data/shared/why_checkin/medlineplus",
  header "true",
  multiLine "true",
  escape "\"",
  quote "\""
);

CREATE LIGHTNING FILESTORE TABLE pubmed FROM WHY_CHECKIN
FORMAT csv
OPTIONS (
  path "file:///home/zetaris/customer-data/shared/why_checkin/pubmed",
  header "true",
  multiLine "true",
  escape "\"",
  quote "\""
);

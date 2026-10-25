CREATE LIGHTNING DATABASE LYFE_HEALTH_CHECKIN DESCRIBE BY "Health check-in agent, user habit log and public health sources" OPTIONS ();

CREATE LIGHTNING FILESTORE TABLE user_log FROM LYFE_HEALTH_CHECKIN
FORMAT csv
OPTIONS (
  path "file:///home/zetaris/customer-data/shared/lyfe_health_checkin/user_log",
  header "true",
  multiLine "true",
  escape "\"",
  quote "\""
);

CREATE LIGHTNING FILESTORE TABLE nutrient_limits FROM LYFE_HEALTH_CHECKIN
FORMAT csv
OPTIONS (
  path "file:///home/zetaris/customer-data/shared/lyfe_health_checkin/nutrient_limits",
  header "true",
  multiLine "true",
  escape "\"",
  quote "\""
);

CREATE LIGHTNING FILESTORE TABLE myhealthfinder FROM LYFE_HEALTH_CHECKIN
FORMAT csv
OPTIONS (
  path "file:///home/zetaris/customer-data/shared/lyfe_health_checkin/myhealthfinder",
  header "true",
  multiLine "true",
  escape "\"",
  quote "\""
);

CREATE LIGHTNING FILESTORE TABLE medlineplus FROM LYFE_HEALTH_CHECKIN
FORMAT csv
OPTIONS (
  path "file:///home/zetaris/customer-data/shared/lyfe_health_checkin/medlineplus",
  header "true",
  multiLine "true",
  escape "\"",
  quote "\""
);

CREATE LIGHTNING FILESTORE TABLE pubmed FROM LYFE_HEALTH_CHECKIN
FORMAT csv
OPTIONS (
  path "file:///home/zetaris/customer-data/shared/lyfe_health_checkin/pubmed",
  header "true",
  multiLine "true",
  escape "\"",
  quote "\""
);

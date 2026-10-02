CREATE TABLE orders (
  order_no INTEGER NOT NULL,
  company_id INTEGER NOT NULL,
  status CHAR(1) NOT NULL,
  paid_at TIMESTAMP,
  fee NUMERIC(19, 4),
  PRIMARY KEY (order_no, company_id)
);

CREATE TABLE company_fees (
  company_id INTEGER NOT NULL,
  service_code VARCHAR(10) NOT NULL,
  fee NUMERIC(19, 4),
  charged_apart CHAR(1) NOT NULL,
  PRIMARY KEY (company_id, service_code)
);

CREATE TABLE services (
  code VARCHAR(10) PRIMARY KEY,
  fee NUMERIC(19, 4)
);

CREATE TABLE accounts (
  account_no CHAR(10) NOT NULL,
  account_type CHAR(3) NOT NULL,
  balance NUMERIC(19, 4) NOT NULL,
  PRIMARY KEY (account_no, account_type)
);

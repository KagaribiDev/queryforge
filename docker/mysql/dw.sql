SET NAMES utf8mb4;

CREATE USER IF NOT EXISTS 'queryforge'@'%' IDENTIFIED BY 'QueryForge.123';
CREATE DATABASE IF NOT EXISTS dw DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
CREATE DATABASE IF NOT EXISTS meta DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
GRANT ALL PRIVILEGES ON dw.* TO 'queryforge'@'%';
GRANT ALL PRIVILEGES ON meta.* TO 'queryforge'@'%';
USE dw;

-- 事实表依赖四张维度表，重复初始化时必须先删除事实表。
DROP TABLE IF EXISTS fact_order;
DROP TABLE IF EXISTS dim_region;
DROP TABLE IF EXISTS dim_customer;
DROP TABLE IF EXISTS dim_product;
DROP TABLE IF EXISTS dim_date;

-- 十进制种子表用于构造1~100000的序列，不依赖存储过程或递归深度配置。
-- 这里不能使用TEMPORARY TABLE：MySQL不允许一条查询用不同别名多次引用同一临时表。
DROP TABLE IF EXISTS seed_digit;
CREATE TABLE seed_digit (digit TINYINT PRIMARY KEY);
INSERT INTO seed_digit VALUES (0), (1), (2), (3), (4), (5), (6), (7), (8), (9);


-- 地区维度：31个省级行政区，region_name采用常见七大地理分区口径。
CREATE TABLE dim_region
(
    region_id   VARCHAR(20) PRIMARY KEY,
    province    VARCHAR(50) NOT NULL,
    region_name VARCHAR(50) NOT NULL,
    country     VARCHAR(50) NOT NULL,
    UNIQUE KEY uk_region_province (province),
    KEY idx_region_name (region_name)
) ENGINE = InnoDB;

INSERT INTO dim_region (region_id, province, region_name, country)
VALUES ('R001', '广东省', '华南', '中国'),
       ('R002', '浙江省', '华东', '中国'),
       ('R003', '四川省', '西南', '中国'),
       ('R004', '北京市', '华北', '中国'),
       ('R005', '上海市', '华东', '中国'),
       ('R006', '湖北省', '华中', '中国'),
       ('R007', '江苏省', '华东', '中国'),
       ('R008', '山东省', '华东', '中国'),
       ('R009', '福建省', '华东', '中国'),
       ('R010', '安徽省', '华东', '中国'),
       ('R011', '江西省', '华东', '中国'),
       ('R012', '天津市', '华北', '中国'),
       ('R013', '河北省', '华北', '中国'),
       ('R014', '山西省', '华北', '中国'),
       ('R015', '内蒙古自治区', '华北', '中国'),
       ('R016', '河南省', '华中', '中国'),
       ('R017', '湖南省', '华中', '中国'),
       ('R018', '广西壮族自治区', '华南', '中国'),
       ('R019', '海南省', '华南', '中国'),
       ('R020', '重庆市', '西南', '中国'),
       ('R021', '贵州省', '西南', '中国'),
       ('R022', '云南省', '西南', '中国'),
       ('R023', '西藏自治区', '西南', '中国'),
       ('R024', '辽宁省', '东北', '中国'),
       ('R025', '吉林省', '东北', '中国'),
       ('R026', '黑龙江省', '东北', '中国'),
       ('R027', '陕西省', '西北', '中国'),
       ('R028', '甘肃省', '西北', '中国'),
       ('R029', '青海省', '西北', '中国'),
       ('R030', '宁夏回族自治区', '西北', '中国'),
       ('R031', '新疆维吾尔自治区', '西北', '中国');


-- 客户维度：2000名客户；性别与四种会员等级采用独立哈希近似均匀分布。
CREATE TABLE dim_customer
(
    customer_id   VARCHAR(20) PRIMARY KEY,
    customer_name VARCHAR(50) NOT NULL,
    gender        VARCHAR(10) NOT NULL,
    member_level  VARCHAR(20) NOT NULL,
    KEY idx_customer_gender (gender),
    KEY idx_customer_member_level (member_level)
) ENGINE = InnoDB;

INSERT INTO dim_customer (customer_id, customer_name, gender, member_level)
SELECT CONCAT('C', LPAD(n, 4, '0')),
       CONCAT(
           ELT(MOD(CRC32(CONCAT(n, ':surname')), 20) + 1,
               '王', '李', '张', '刘', '陈', '杨', '黄', '赵', '周', '吴',
               '徐', '孙', '胡', '朱', '高', '林', '何', '郭', '马', '罗'),
           ELT(MOD(CRC32(CONCAT(n, ':given_name')), 20) + 1,
               '晨', '宇', '欣', '怡', '浩', '婷', '博', '雪', '杰', '敏',
               '磊', '静', '睿', '娜', '航', '琪', '峰', '琳', '涛', '悦'),
           LPAD(n, 4, '0')
       ),
       IF(MOD(CRC32(CONCAT(n, ':gender')), 2) = 0, '女', '男'),
       ELT(MOD(CRC32(CONCAT(n, ':member_level')), 4) + 1, '青铜', '白银', '黄金', '铂金')
FROM (
    SELECT ones.digit + tens.digit * 10 + hundreds.digit * 100 + thousands.digit * 1000 + 1 AS n
    FROM seed_digit ones
    CROSS JOIN seed_digit tens
    CROSS JOIN seed_digit hundreds
    CROSS JOIN seed_digit thousands
) sequence_customer
WHERE n <= 2000;


-- 商品维度：200个商品，品类、品牌和价格分别使用不同哈希盐值随机生成。
CREATE TABLE dim_product
(
    product_id   VARCHAR(20) PRIMARY KEY,
    product_name VARCHAR(200) NOT NULL,
    category     VARCHAR(50) NOT NULL,
    brand        VARCHAR(50) NOT NULL,
    KEY idx_product_category (category),
    KEY idx_product_brand (brand)
) ENGINE = InnoDB;

INSERT INTO dim_product (product_id, product_name, category, brand)
SELECT CONCAT('P', LPAD(n, 3, '0')),
       CONCAT(brand, ' ', product_kind, ' ', LPAD(n, 3, '0')),
       category,
       brand
FROM (
    SELECT n,
           category,
           CASE category
               WHEN '手机数码' THEN ELT(MOD(CRC32(CONCAT(n, ':brand')), 6) + 1, '苹果', '三星', '华为', '小米', '荣耀', 'OPPO')
               WHEN '家用电器' THEN ELT(MOD(CRC32(CONCAT(n, ':brand')), 6) + 1, '美的', '海尔', '格力', '苏泊尔', '戴森', '小熊')
               WHEN '鞋靴' THEN ELT(MOD(CRC32(CONCAT(n, ':brand')), 6) + 1, '耐克', '阿迪达斯', '安踏', '李宁', '特步', '彪马')
               WHEN '服饰' THEN ELT(MOD(CRC32(CONCAT(n, ':brand')), 6) + 1, '优衣库', '李维斯', '太平鸟', '森马', '海澜之家', '蕉内')
               WHEN '食品饮料' THEN ELT(MOD(CRC32(CONCAT(n, ':brand')), 6) + 1, '雀巢', '蒙牛', '伊利', '农夫山泉', '元气森林', '统一')
               ELSE ELT(MOD(CRC32(CONCAT(n, ':brand')), 6) + 1, '乐事', '奥利奥', '三只松鼠', '良品铺子', '洽洽', '旺旺')
           END AS brand,
           CASE category
               WHEN '手机数码' THEN '智能设备'
               WHEN '家用电器' THEN '品质家电'
               WHEN '鞋靴' THEN '运动鞋'
               WHEN '服饰' THEN '经典服饰'
               WHEN '食品饮料' THEN '营养饮品'
               ELSE '休闲零食'
           END AS product_kind
    FROM (
        SELECT n, ELT(MOD(CRC32(CONCAT(n, ':category')), 6) + 1,
                      '手机数码', '家用电器', '鞋靴', '服饰', '食品饮料', '休闲零食') AS category
        FROM (
            SELECT ones.digit + tens.digit * 10 + hundreds.digit * 100 + 1 AS n
            FROM seed_digit ones
            CROSS JOIN seed_digit tens
            CROSS JOIN seed_digit hundreds
        ) product_sequence
        WHERE n <= 200
    ) product_category
) product_detail;


-- 日期维度：2025全年365天。
CREATE TABLE dim_date
(
    date_id   INT PRIMARY KEY,
    `year`    INT NOT NULL,
    quarter   VARCHAR(2) NOT NULL,
    `month`   INT NOT NULL,
    `day`     INT NOT NULL,
    full_date DATE NOT NULL,
    UNIQUE KEY uk_date_full_date (full_date),
    KEY idx_date_year_month (`year`, `month`),
    KEY idx_date_year_quarter (`year`, quarter)
) ENGINE = InnoDB;

INSERT INTO dim_date (date_id, `year`, quarter, `month`, `day`, full_date)
SELECT CAST(DATE_FORMAT(full_date, '%Y%m%d') AS UNSIGNED),
       YEAR(full_date), CONCAT('Q', QUARTER(full_date)), MONTH(full_date), DAY(full_date), full_date
FROM (
    SELECT DATE_ADD('2025-01-01', INTERVAL n DAY) AS full_date
    FROM (
        SELECT ones.digit + tens.digit * 10 + hundreds.digit * 100 AS n
        FROM seed_digit ones
        CROSS JOIN seed_digit tens
        CROSS JOIN seed_digit hundreds
    ) sequence_date
    WHERE n < 365
) dates;


-- 订单事实表：四个维度键均有真实外键约束，并针对常用联查建立索引。
CREATE TABLE fact_order
(
    order_id       VARCHAR(30) PRIMARY KEY,
    customer_id    VARCHAR(20) NOT NULL,
    product_id     VARCHAR(20) NOT NULL,
    date_id        INT NOT NULL,
    region_id      VARCHAR(20) NOT NULL,
    order_quantity INT NOT NULL,
    order_amount   DECIMAL(12, 2) NOT NULL,
    CONSTRAINT chk_order_quantity CHECK (order_quantity BETWEEN 1 AND 5),
    CONSTRAINT chk_order_amount CHECK (order_amount >= 0),
    CONSTRAINT fk_order_customer FOREIGN KEY (customer_id) REFERENCES dim_customer (customer_id),
    CONSTRAINT fk_order_product FOREIGN KEY (product_id) REFERENCES dim_product (product_id),
    CONSTRAINT fk_order_date FOREIGN KEY (date_id) REFERENCES dim_date (date_id),
    CONSTRAINT fk_order_region FOREIGN KEY (region_id) REFERENCES dim_region (region_id),
    KEY idx_order_customer (customer_id),
    KEY idx_order_product (product_id),
    KEY idx_order_date (date_id),
    KEY idx_order_region (region_id),
    KEY idx_order_date_product (date_id, product_id),
    KEY idx_order_date_region (date_id, region_id),
    KEY idx_order_customer_date (customer_id, date_id)
) ENGINE = InnoDB;

-- 带不同盐值的独立哈希随机分配：日期、客户、商品、地区、数量互不绑定，初始化结果可复现。
INSERT INTO fact_order
    (order_id, customer_id, product_id, date_id, region_id, order_quantity, order_amount)
SELECT CONCAT('ORD', DATE_FORMAT(g.order_date, '%Y%m%d'), LPAD(g.n, 6, '0')),
       CONCAT('C', LPAD(g.customer_no, 4, '0')),
       CONCAT('P', LPAD(g.product_no, 3, '0')),
       CAST(DATE_FORMAT(g.order_date, '%Y%m%d') AS UNSIGNED),
       CONCAT('R', LPAD(g.region_no, 3, '0')),
       g.quantity,
       ROUND(g.quantity
             * CASE p.category
                   WHEN '手机数码' THEN 1000 + MOD(CRC32(CONCAT(g.product_no, ':price')), 8000)
                   WHEN '家用电器' THEN 300 + MOD(CRC32(CONCAT(g.product_no, ':price')), 5200)
                   WHEN '鞋靴' THEN 150 + MOD(CRC32(CONCAT(g.product_no, ':price')), 1350)
                   WHEN '服饰' THEN 80 + MOD(CRC32(CONCAT(g.product_no, ':price')), 920)
                   WHEN '食品饮料' THEN 15 + MOD(CRC32(CONCAT(g.product_no, ':price')), 185)
                   ELSE 8 + MOD(CRC32(CONCAT(g.product_no, ':price')), 92)
               END
             * (0.85 + MOD(CRC32(CONCAT(g.n, ':discount')), 1501) / 10000), 2)
FROM (
    SELECT n,
           DATE_ADD('2025-01-01', INTERVAL MOD(CRC32(CONCAT(n, ':date')), 365) DAY) AS order_date,
           MOD(CRC32(CONCAT(n, ':customer')), 2000) + 1 AS customer_no,
           MOD(CRC32(CONCAT(n, ':product')), 200) + 1 AS product_no,
           MOD(CRC32(CONCAT(n, ':region')), 31) + 1 AS region_no,
           MOD(CRC32(CONCAT(n, ':quantity')), 5) + 1 AS quantity
    FROM (
        SELECT ones.digit
             + tens.digit * 10
             + hundreds.digit * 100
             + thousands.digit * 1000
             + ten_thousands.digit * 10000
             + 1 AS n
        FROM seed_digit ones
        CROSS JOIN seed_digit tens
        CROSS JOIN seed_digit hundreds
        CROSS JOIN seed_digit thousands
        CROSS JOIN seed_digit ten_thousands
    ) sequence_order
) g
JOIN dim_product p ON p.product_id = CONCAT('P', LPAD(g.product_no, 3, '0'));

DROP TABLE seed_digit;

-- 初始化自检：预期31/2000/200/365/100000，且孤儿订单数为0。
SELECT (SELECT COUNT(*) FROM dim_region) AS region_count,
       (SELECT COUNT(*) FROM dim_customer) AS customer_count,
       (SELECT COUNT(*) FROM dim_product) AS product_count,
       (SELECT COUNT(*) FROM dim_date) AS date_count,
       (SELECT COUNT(*) FROM fact_order) AS order_count,
       (SELECT COUNT(*)
        FROM fact_order o
        LEFT JOIN dim_customer c ON o.customer_id = c.customer_id
        LEFT JOIN dim_product p ON o.product_id = p.product_id
        LEFT JOIN dim_date d ON o.date_id = d.date_id
        LEFT JOIN dim_region r ON o.region_id = r.region_id
        WHERE c.customer_id IS NULL OR p.product_id IS NULL
           OR d.date_id IS NULL OR r.region_id IS NULL) AS orphan_order_count;

-- 分布自检：观察每个维度成员承接订单数的最小值、最大值和平均值，便于发现异常倾斜。
SELECT 'date' AS dimension_name, MIN(order_count) AS min_orders,
       MAX(order_count) AS max_orders, ROUND(AVG(order_count), 2) AS avg_orders
FROM (SELECT date_id, COUNT(*) AS order_count FROM fact_order GROUP BY date_id) date_distribution
UNION ALL
SELECT 'customer', MIN(order_count), MAX(order_count), ROUND(AVG(order_count), 2)
FROM (SELECT customer_id, COUNT(*) AS order_count FROM fact_order GROUP BY customer_id) customer_distribution
UNION ALL
SELECT 'product', MIN(order_count), MAX(order_count), ROUND(AVG(order_count), 2)
FROM (SELECT product_id, COUNT(*) AS order_count FROM fact_order GROUP BY product_id) product_distribution
UNION ALL
SELECT 'region', MIN(order_count), MAX(order_count), ROUND(AVG(order_count), 2)
FROM (SELECT region_id, COUNT(*) AS order_count FROM fact_order GROUP BY region_id) region_distribution;

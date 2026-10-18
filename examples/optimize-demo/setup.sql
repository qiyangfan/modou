-- 案例二场景搭建:orders 表 5 万行确定性合成数据(无随机量,可复现)。
-- 在目标库执行本文件后,用 modou snapshot capture --sample-rows 采集采样基线。
DROP TABLE IF EXISTS orders;
CREATE TABLE orders (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '订单号',
    user_id BIGINT UNSIGNED NOT NULL COMMENT '下单用户',
    amount DECIMAL(12, 2) NOT NULL DEFAULT 0.00 COMMENT '订单金额',
    status TINYINT NOT NULL DEFAULT 0 COMMENT '状态:0 待支付 / 1 已支付',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '下单时间',
    PRIMARY KEY (id),
    KEY idx_user_id (user_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '订单表';

SET SESSION cte_max_recursion_depth = 60000;

INSERT INTO orders (user_id, amount, status, created_at)
WITH RECURSIVE seq(n) AS (
    SELECT 1 UNION ALL SELECT n + 1 FROM seq WHERE n < 50000
)
SELECT
    1 + (n % 100),                            -- user_id 1..100,每用户约 50 单
    ROUND(((n * 37) % 900) + ((n % 100) / 100), 2),
    n % 2,                                    -- status 0/1 各半
    NOW() - INTERVAL n MINUTE
FROM seq;

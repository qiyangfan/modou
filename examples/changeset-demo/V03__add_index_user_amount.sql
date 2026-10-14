-- 用户维度金额统计索引（INPLACE，不阻塞写）
ALTER TABLE orders ADD INDEX idx_user_amount (user_id, amount);

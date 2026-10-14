-- 用户订单数统计过程
DELIMITER $$
CREATE PROCEDURE sp_order_count(IN p_user_id BIGINT UNSIGNED, OUT p_total INT)
BEGIN
    SELECT COUNT(*) INTO p_total FROM orders WHERE user_id = p_user_id;
END$$
DELIMITER ;

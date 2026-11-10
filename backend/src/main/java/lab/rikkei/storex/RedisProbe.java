package lab.rikkei.storex;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.data.redis.core.RedisCallback;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

@Service
public class RedisProbe implements ApplicationRunner {
    private static final Logger log = LoggerFactory.getLogger(RedisProbe.class);
    private final StringRedisTemplate redis;

    public RedisProbe(StringRedisTemplate redis) {
        this.redis = redis;
    }

    public String ping() {
        String response = redis.execute((RedisCallback<String>) connection -> connection.ping());
        if (!"PONG".equals(response)) {
            throw new IllegalStateException("Unexpected Redis PING response");
        }
        log.info("REDIS_CHECK SUCCESS command=PING response={}", response);
        return response;
    }

    @Override
    public void run(ApplicationArguments args) {
        // A real PING is required for successful application startup.
        ping();
    }
}

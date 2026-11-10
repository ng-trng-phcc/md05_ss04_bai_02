package lab.rikkei.storex;

import java.time.Instant;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class RedisCheckController {
    private static final Logger log = LoggerFactory.getLogger(RedisCheckController.class);
    private final RedisProbe probe;

    public RedisCheckController(RedisProbe probe) {
        this.probe = probe;
    }

    @GetMapping("/redis-check")
    public ResponseEntity<CheckResponse> check() {
        try {
            String response = probe.ping();
            return ResponseEntity.ok(new CheckResponse("UP", true, true, response,
                    "Redis PING executed successfully", Instant.now()));
        } catch (DataAccessException | IllegalStateException ex) {
            log.warn("REDIS_CHECK FAILURE type={}", ex.getClass().getSimpleName());
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).body(
                    new CheckResponse("DOWN", false, false, null,
                            "Redis PING failed", Instant.now()));
        }
    }

    public record CheckResponse(String status, boolean redisReachable, boolean pingExecuted,
                                String response, String message, Instant timestamp) {
    }
}

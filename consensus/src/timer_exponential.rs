use std::future::Future;
use std::pin::Pin;
use std::task::{Context, Poll};
use tokio::time::{sleep, Duration, Instant, Sleep};

#[cfg(test)]
#[path = "tests/timer_tests.rs"]
pub mod timer_tests;

pub struct Timer {
    current_timeout: u64,
    base_timeout: u64,
    max_timeout: u64,
    consecutive_timeouts: u32,
    round_start_time: Option<Instant>,
    sleep: Pin<Box<Sleep>>,
}

impl Timer {
    pub fn new(initial_timeout: u64) -> Self {
        let sleep = Box::pin(sleep(Duration::from_millis(initial_timeout)));
        Self {
            current_timeout: initial_timeout,
            base_timeout: initial_timeout,
            max_timeout: 30_000,
            consecutive_timeouts: 0,
            round_start_time: Some(Instant::now()),
            sleep,
        }
    }

    pub fn start_round(&mut self) {
        self.round_start_time = Some(Instant::now());
    }

    pub fn on_round_complete(&mut self) {
        // Round succeeded - reset exponential backoff
        self.consecutive_timeouts = 0;
        self.current_timeout = self.base_timeout;
        
        log::debug!(
            "Exponential backoff: Round succeeded, reset to base {}ms",
            self.current_timeout
        );
    }

    pub fn current_timeout(&self) -> u64 {
        self.current_timeout
    }

    pub fn reset(&mut self) {
        // Check if previous round actually timed out
        if let Some(start_time) = self.round_start_time {
            let elapsed_ms = start_time.elapsed().as_millis() as u64;
            
            // If elapsed time >= current timeout, it means we timed out
            if elapsed_ms >= self.current_timeout {
                // Actual timeout - use exponential backoff
                self.consecutive_timeouts += 1;
                self.current_timeout = (self.base_timeout * (2_u64.pow(self.consecutive_timeouts)))
                    .min(self.max_timeout);
                
                log::debug!(
                    "Exponential backoff: timeout detected ({}ms), increasing to {}ms",
                    elapsed_ms, self.current_timeout
                );
            }
        }
        
        let timeout = self.current_timeout;
        self.sleep = Box::pin(sleep(Duration::from_millis(timeout)));
    }
}

impl Future for Timer {
    type Output = ();

    fn poll(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        self.sleep.as_mut().poll(cx)
    }
}

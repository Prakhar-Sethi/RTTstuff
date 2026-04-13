use std::future::Future;
use std::pin::Pin;
use std::task::{Context, Poll};
use tokio::time::{sleep, Duration, Instant, Sleep};

#[cfg(test)]
#[path = "tests/timer_tests.rs"]
pub mod timer_tests;

pub struct Timer {
    estimated_rtt: f64,
    dev_rtt: f64,
    alpha: f64,
    beta: f64,
    current_timeout: u64,
    min_timeout: u64,
    max_timeout: u64,
    round_start_time: Option<Instant>,
    sleep: Pin<Box<Sleep>>,
}

impl Timer {
    pub fn new(initial_timeout: u64) -> Self {
        let estimated_rtt = initial_timeout as f64;
        let dev_rtt = initial_timeout as f64 / 4.0;
        let sleep = Box::pin(sleep(Duration::from_millis(initial_timeout)));
        Self {
            estimated_rtt,
            dev_rtt,
            alpha: 0.125,
            beta: 0.25,
            current_timeout: initial_timeout,
            min_timeout: 500,
            max_timeout: 30_000,
            round_start_time: None,
            sleep,
        }
    }
    
    pub fn start_round(&mut self) {
        self.round_start_time = Some(Instant::now());
    }
    
    pub fn on_round_complete(&mut self) {
        self.current_timeout = 5000;
    }
    
    pub fn current_timeout(&self) -> u64 {
        self.current_timeout
    }
    
    pub fn reset(&mut self) {
        self.start_round();
        self.sleep
            .as_mut()
            .reset(Instant::now() + Duration::from_millis(self.current_timeout));
    }
}

impl Future for Timer {
    type Output = ();
    fn poll(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<()> {
        self.sleep.as_mut().poll(cx)
    }
}
